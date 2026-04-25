import os
import random
import string
from datetime import datetime, timezone
from functools import wraps

from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from flask_socketio import SocketIO, emit
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'change-this-in-production-xyz987')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///votes.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

db = SQLAlchemy(app)
socketio = SocketIO(app, cors_allowed_origins="*")
limiter = Limiter(key_func=get_remote_address, app=app, default_limits=["200 per hour"])

ADMIN_PASSWORD_HASH = generate_password_hash(os.environ.get('ADMIN_PASSWORD', 'admin1234'))

# ─── Models ──────────────────────────────────────────────────────────────────

class Voter(db.Model):
    __tablename__ = 'voters'
    id = db.Column(db.Integer, primary_key=True)
    unique_code = db.Column(db.String(12), unique=True, nullable=False, index=True)
    has_voted = db.Column(db.Boolean, default=False, nullable=False)
    vote_time = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    vote = db.relationship('Vote', backref='voter', uselist=False)

class Candidate(db.Model):
    __tablename__ = 'candidates'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    position = db.Column(db.String(100), nullable=True)
    vote_count = db.Column(db.Integer, default=0, nullable=False)
    votes = db.relationship('Vote', backref='candidate')

class Vote(db.Model):
    __tablename__ = 'votes'
    id = db.Column(db.Integer, primary_key=True)
    voter_id = db.Column(db.Integer, db.ForeignKey('voters.id'), nullable=False, unique=True)
    candidate_id = db.Column(db.Integer, db.ForeignKey('candidates.id'), nullable=False)
    timestamp = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

class ElectionSettings(db.Model):
    __tablename__ = 'election_settings'
    id = db.Column(db.Integer, primary_key=True)
    start_time = db.Column(db.DateTime, nullable=True)
    end_time = db.Column(db.DateTime, nullable=True)
    election_name = db.Column(db.String(200), default='General Election')
    is_active = db.Column(db.Boolean, default=False)

# ─── Helpers ─────────────────────────────────────────────────────────────────

def generate_voter_code():
    chars = string.ascii_uppercase + string.digits
    while True:
        code = 'VOTE-' + ''.join(random.choices(chars, k=6))
        if not Voter.query.filter_by(unique_code=code).first():
            return code

def get_settings():
    s = ElectionSettings.query.first()
    if not s:
        s = ElectionSettings()
        db.session.add(s)
        db.session.commit()
    return s

def voting_status():
    s = get_settings()
    now = datetime.now(timezone.utc)
    if not s.start_time or not s.end_time:
        return 'not_configured'
    start = s.start_time.replace(tzinfo=timezone.utc) if s.start_time.tzinfo is None else s.start_time
    end = s.end_time.replace(tzinfo=timezone.utc) if s.end_time.tzinfo is None else s.end_time
    if now < start:
        return 'not_started'
    if now > end:
        return 'ended'
    return 'open'

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('admin_logged_in'):
            return jsonify({'error': 'Unauthorized'}), 401
        return f(*args, **kwargs)
    return decorated

def get_results_data():
    candidates = Candidate.query.all()
    total = sum(c.vote_count for c in candidates)
    return [
        {
            'id': c.id,
            'name': c.name,
            'position': c.position,
            'vote_count': c.vote_count,
            'percentage': round((c.vote_count / total * 100), 1) if total > 0 else 0
        }
        for c in candidates
    ], total

# ─── Public Routes ────────────────────────────────────────────────────────────

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/vote')
def vote_page():
    voter_code = session.get('voter_code')
    if not voter_code:
        return redirect('/')
    voter = Voter.query.filter_by(unique_code=voter_code).first()
    if not voter or voter.has_voted:
        session.pop('voter_code', None)
        return redirect('/')
    status = voting_status()
    if status != 'open':
        return render_template('vote.html', status=status, voter=voter, candidates=[])
    candidates = Candidate.query.all()
    return render_template('vote.html', status=status, voter=voter, candidates=candidates)

@app.route('/results')
def results_page():
    candidates, total = get_results_data()
    settings = get_settings()
    return render_template('results.html', candidates=candidates, total=total, settings=settings)

# ─── Voter API ────────────────────────────────────────────────────────────────

@app.route('/api/validate-voter', methods=['POST'])
@limiter.limit("10 per minute")
def validate_voter():
    data = request.get_json()
    if not data or 'voter_id' not in data:
        return jsonify({'valid': False, 'message': 'No voter ID provided'}), 400

    code = data['voter_id'].strip().upper()
    voter = Voter.query.filter_by(unique_code=code).first()

    if not voter:
        return jsonify({'valid': False, 'message': 'Invalid voter ID. Please check and try again.'})
    if voter.has_voted:
        return jsonify({'valid': False, 'message': 'This voter ID has already been used.'})

    status = voting_status()
    if status == 'not_configured':
        return jsonify({'valid': False, 'message': 'Election has not been configured yet.'})
    if status == 'not_started':
        s = get_settings()
        return jsonify({'valid': False, 'message': f'Voting has not started yet. Starts at {s.start_time.strftime("%b %d, %Y %H:%M UTC")}.'})
    if status == 'ended':
        return jsonify({'valid': False, 'message': 'Voting has ended. Thank you.'})

    session['voter_code'] = code
    session.permanent = False
    return jsonify({'valid': True, 'message': 'Voter ID verified. Redirecting to ballot...'})

@app.route('/api/submit-vote', methods=['POST'])
@limiter.limit("5 per minute")
def submit_vote():
    voter_code = session.get('voter_code')
    if not voter_code:
        return jsonify({'success': False, 'message': 'Session expired. Please validate your ID again.'}), 401

    voter = Voter.query.filter_by(unique_code=voter_code).first()
    if not voter:
        return jsonify({'success': False, 'message': 'Invalid session.'}), 401
    if voter.has_voted:
        session.pop('voter_code', None)
        return jsonify({'success': False, 'message': 'You have already voted.'}), 403

    status = voting_status()
    if status != 'open':
        return jsonify({'success': False, 'message': 'Voting is not currently open.'}), 403

    data = request.get_json()
    if not data or 'candidate_id' not in data:
        return jsonify({'success': False, 'message': 'No candidate selected.'}), 400

    candidate = Candidate.query.get(data['candidate_id'])
    if not candidate:
        return jsonify({'success': False, 'message': 'Invalid candidate.'}), 400

    try:
        vote = Vote(voter_id=voter.id, candidate_id=candidate.id)
        voter.has_voted = True
        voter.vote_time = datetime.now(timezone.utc)
        candidate.vote_count += 1
        db.session.add(vote)
        db.session.commit()
        session.pop('voter_code', None)

        results, total = get_results_data()
        socketio.emit('vote_update', {'results': results, 'total': total})

        return jsonify({'success': True, 'message': 'Your vote has been recorded. Thank you!'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': 'An error occurred. Please try again.'}), 500

@app.route('/api/results')
def api_results():
    results, total = get_results_data()
    settings = get_settings()
    return jsonify({
        'results': results,
        'total': total,
        'status': voting_status(),
        'election_name': settings.election_name
    })

# ─── Admin API ────────────────────────────────────────────────────────────────

@app.route('/admin')
def admin_page():
    return render_template('admin.html')

@app.route('/api/admin/login', methods=['POST'])
@limiter.limit("5 per minute")
def admin_login():
    data = request.get_json()
    if data and check_password_hash(ADMIN_PASSWORD_HASH, data.get('password', '')):
        session['admin_logged_in'] = True
        return jsonify({'success': True})
    return jsonify({'success': False, 'message': 'Invalid password'}), 401

@app.route('/api/admin/logout', methods=['POST'])
def admin_logout():
    session.pop('admin_logged_in', None)
    return jsonify({'success': True})

@app.route('/api/admin/status')
@admin_required
def admin_status():
    return jsonify({'logged_in': True})

@app.route('/api/admin/generate-voters', methods=['POST'])
@admin_required
def generate_voters():
    data = request.get_json()
    count = min(int(data.get('count', 100)), 500)
    new_voters = []
    for _ in range(count):
        code = generate_voter_code()
        v = Voter(unique_code=code)
        db.session.add(v)
        new_voters.append(code)
    db.session.commit()
    return jsonify({'success': True, 'count': count, 'codes': new_voters})

@app.route('/api/admin/voters')
@admin_required
def list_voters():
    voters = Voter.query.order_by(Voter.created_at.desc()).all()
    return jsonify([{
        'id': v.id,
        'unique_code': v.unique_code,
        'has_voted': v.has_voted,
        'vote_time': v.vote_time.isoformat() if v.vote_time else None,
        'created_at': v.created_at.isoformat()
    } for v in voters])

@app.route('/api/admin/candidates', methods=['GET'])
@admin_required
def list_candidates():
    candidates = Candidate.query.all()
    return jsonify([{'id': c.id, 'name': c.name, 'position': c.position, 'vote_count': c.vote_count} for c in candidates])

@app.route('/api/admin/candidates', methods=['POST'])
@admin_required
def add_candidate():
    data = request.get_json()
    if not data or not data.get('name'):
        return jsonify({'success': False, 'message': 'Name required'}), 400
    c = Candidate(name=data['name'], position=data.get('position', ''))
    db.session.add(c)
    db.session.commit()
    return jsonify({'success': True, 'id': c.id})

@app.route('/api/admin/candidates/<int:cid>', methods=['PUT'])
@admin_required
def update_candidate(cid):
    c = Candidate.query.get_or_404(cid)
    data = request.get_json()
    if data.get('name'):
        c.name = data['name']
    if 'position' in data:
        c.position = data['position']
    db.session.commit()
    return jsonify({'success': True})

@app.route('/api/admin/candidates/<int:cid>', methods=['DELETE'])
@admin_required
def delete_candidate(cid):
    c = Candidate.query.get_or_404(cid)
    db.session.delete(c)
    db.session.commit()
    return jsonify({'success': True})

@app.route('/api/admin/settings', methods=['GET'])
@admin_required
def get_election_settings():
    s = get_settings()
    return jsonify({
        'election_name': s.election_name,
        'start_time': s.start_time.isoformat() if s.start_time else None,
        'end_time': s.end_time.isoformat() if s.end_time else None,
        'is_active': s.is_active,
        'status': voting_status()
    })

@app.route('/api/admin/settings', methods=['POST'])
@admin_required
def update_settings():
    data = request.get_json()
    s = get_settings()
    if 'election_name' in data:
        s.election_name = data['election_name']
    if 'start_time' in data and data['start_time']:
        s.start_time = datetime.fromisoformat(data['start_time'].replace('Z', '+00:00'))
    if 'end_time' in data and data['end_time']:
        s.end_time = datetime.fromisoformat(data['end_time'].replace('Z', '+00:00'))
    db.session.commit()
    return jsonify({'success': True, 'status': voting_status()})

@app.route('/api/admin/reset', methods=['POST'])
@admin_required
def reset_election():
    Vote.query.delete()
    Voter.query.update({'has_voted': False, 'vote_time': None})
    Candidate.query.update({'vote_count': 0})
    db.session.commit()
    results, total = get_results_data()
    socketio.emit('vote_update', {'results': results, 'total': total})
    return jsonify({'success': True, 'message': 'Election reset successfully.'})

@app.route('/api/admin/stats')
@admin_required
def admin_stats():
    total_voters = Voter.query.count()
    voted = Voter.query.filter_by(has_voted=True).count()
    results, total_votes = get_results_data()
    return jsonify({
        'total_voters': total_voters,
        'voted': voted,
        'not_voted': total_voters - voted,
        'turnout': round(voted / total_voters * 100, 1) if total_voters > 0 else 0,
        'total_votes': total_votes,
        'status': voting_status()
    })

# ─── SocketIO ─────────────────────────────────────────────────────────────────

@socketio.on('connect')
def on_connect():
    results, total = get_results_data()
    emit('vote_update', {'results': results, 'total': total})

# ─── Init ─────────────────────────────────────────────────────────────────────

def init_db():
    with app.app_context():
        db.create_all()
        if not ElectionSettings.query.first():
            db.session.add(ElectionSettings())
            db.session.commit()

if __name__ == '__main__':
    init_db()
    socketio.run(app, debug=True, host='0.0.0.0', port=5000)
