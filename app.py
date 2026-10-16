import os
import secrets
import hashlib
from datetime import datetime, timezone
from functools import wraps
from flask import Flask, render_template, request, jsonify, session
from flask_sqlalchemy import SQLAlchemy
from flask_socketio import SocketIO
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy.exc import IntegrityError

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'local-development-change-this-secret')
url = os.environ.get('DATABASE_URL', 'sqlite:///election.db')
if url.startswith('postgres://'): url = url.replace('postgres://', 'postgresql://', 1)
app.config['SQLALCHEMY_DATABASE_URI'] = url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = os.environ.get('COOKIE_SECURE', '0') == '1'
db = SQLAlchemy(app)
socketio = SocketIO(app, cors_allowed_origins=None, message_queue=os.environ.get('REDIS_URL') or None, async_mode='threading')

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(60), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    is_admin = db.Column(db.Boolean, default=False, nullable=False)

class Vote(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), unique=True, nullable=False)
    candidate = db.Column(db.String(20), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

class AnonymousVote(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    voter_hash = db.Column(db.String(64), unique=True, nullable=False)
    candidate = db.Column(db.String(20), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

class Setting(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    status = db.Column(db.String(20), default='open', nullable=False)

CANDIDATES = [
    {'id':'shardul','name':'Shardul','image':'/static/uploads/shardul.jpeg'},
    {'id':'sattu','name':'Sattu','image':'/static/uploads/default-avatar.svg'},
    {'id':'aash','name':'Aash','image':'/static/uploads/aash.webp'}]

def status():
    return db.session.get(Setting, 1).status

def results():
    from sqlalchemy import func
    rows = db.session.query(Vote.candidate, func.count(Vote.id)).group_by(Vote.candidate).all()
    counts = dict(rows)
    anonymous_rows = db.session.query(AnonymousVote.candidate, func.count(AnonymousVote.id)).group_by(AnonymousVote.candidate).all()
    for candidate, count in anonymous_rows:
        counts[candidate] = counts.get(candidate, 0) + count
    total = sum(counts.values())
    candidates = [{**c, 'votes':counts.get(c['id'], 0), 'percent':round(100*counts.get(c['id'], 0)/total, 1) if total else 0} for c in CANDIDATES]
    maximum = max((c['votes'] for c in candidates), default=0)
    leaders = [c['name'] for c in candidates if c['votes']==maximum]
    return {'candidates':candidates,'total':total,'leader':leaders[0] if maximum and len(leaders)==1 else ('Tie' if maximum else 'No votes yet'),'status':status()}

def identity():
    uid = session.get('user_id')
    u = db.session.get(User, uid) if uid else None
    return {'username':u.username if u else None,'is_admin':bool(u and u.is_admin),'voted':bool(u and Vote.query.filter_by(user_id=u.id).first())}

def admin_required(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        u = db.session.get(User, session['user_id']) if session.get('user_id') else None
        if not u or not u.is_admin: return jsonify(error='Admin access required'), 403
        return f(*args, **kwargs)
    return wrapped

@app.get('/')
def home(): return render_template('index.html')

@app.get('/api/results')
def api_results(): return jsonify(results())

@app.get('/api/me')
def api_me(): return jsonify(identity())

@app.post('/api/register')
def register():
    data = request.get_json(silent=True) or {}
    name = str(data.get('username','')).strip().lower()
    pw = str(data.get('password',''))
    if not (3 <= len(name) <= 60) or not name.replace('_','').isalnum() or len(pw)<8:
        return jsonify(error='Username: 3–60 letters/numbers/underscores. Password: at least 8 characters.'),400
    u = User(username=name, password_hash=generate_password_hash(pw))
    db.session.add(u)
    try: db.session.commit()
    except IntegrityError:
        db.session.rollback(); return jsonify(error='Username already taken'),409
    session.clear(); session['user_id']=u.id
    return jsonify(ok=True, me=identity())

@app.post('/api/login')
def login():
    data = request.get_json(silent=True) or {}
    u = User.query.filter_by(username=str(data.get('username','')).strip().lower()).first()
    if not u or not check_password_hash(u.password_hash,str(data.get('password',''))):
        return jsonify(error='Invalid username or password'),401
    session.clear(); session['user_id']=u.id
    return jsonify(ok=True, me=identity())

@app.post('/api/logout')
def logout():
    session.clear(); return jsonify(ok=True)

@app.get('/api/voter-status')
def voter_status():
    token = session.get('anonymous_voter_token')
    hashed = hashlib.sha256(token.encode()).hexdigest() if token else None
    voted = bool(hashed and AnonymousVote.query.filter_by(voter_hash=hashed).first())
    return jsonify(voted=voted)

@app.post('/api/vote')
def vote():
    candidate = (request.get_json(silent=True) or {}).get('candidate')
    if candidate not in [c['id'] for c in CANDIDATES]: return jsonify(error='Invalid candidate'),400
    if status() != 'open': return jsonify(error='Voting is not open'),403
    token = session.get('anonymous_voter_token')
    if not token:
        token = secrets.token_urlsafe(32)
        session['anonymous_voter_token'] = token
    voter_hash = hashlib.sha256(token.encode()).hexdigest()
    db.session.add(AnonymousVote(voter_hash=voter_hash,candidate=candidate))
    try: db.session.commit()
    except IntegrityError:
        db.session.rollback(); return jsonify(error='You have already voted from this browser'),409
    fresh = results()
    socketio.emit('vote_update',fresh)
    return jsonify(ok=True, results=fresh)

@app.get('/api/admin/stats')
@admin_required
def stats(): return jsonify(results=results(), registered=AnonymousVote.query.count())

@app.post('/api/admin/status')
@admin_required
def change_status():
    new = (request.get_json(silent=True) or {}).get('status')
    if new not in ('open','paused','closed'): return jsonify(error='Invalid status'),400
    db.session.get(Setting,1).status = new
    db.session.commit()
    fresh=results(); socketio.emit('vote_update',fresh)
    return jsonify(ok=True, results=fresh)

@app.post('/api/admin/login')
def admin_login():
    data = request.get_json(silent=True) or {}
    u = User.query.filter_by(username=str(data.get('username','')).strip().lower(), is_admin=True).first()
    if not u or not check_password_hash(u.password_hash, str(data.get('password',''))):
        return jsonify(error='Invalid admin credentials'),401
    session['user_id'] = u.id
    return jsonify(ok=True)

@app.post('/api/admin/logout')
@admin_required
def admin_logout():
    session.pop('user_id', None)
    return jsonify(ok=True)

@app.get('/admin')
def admin_page(): return render_template('admin.html')

@socketio.on('connect')
def connected():
    from flask_socketio import emit
    emit('vote_update', results())

with app.app_context():
    db.create_all()
    if not db.session.get(Setting,1): db.session.add(Setting(id=1,status='open')); db.session.commit()
    admin_name=os.environ.get('ADMIN_USERNAME')
    admin_pass=os.environ.get('ADMIN_PASSWORD')
    if admin_name and admin_pass and len(admin_pass)>=8 and not User.query.filter_by(username=admin_name.lower()).first():
        db.session.add(User(username=admin_name.lower(),password_hash=generate_password_hash(admin_pass),is_admin=True))
        db.session.commit()

if __name__=='__main__':
    socketio.run(app,host='0.0.0.0',port=int(os.environ.get('PORT',5001)),debug=os.environ.get('FLASK_DEBUG')=='1',allow_unsafe_werkzeug=True)
