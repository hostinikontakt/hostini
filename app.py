Tak, rozumiem. Poniżej znajduje się pełny, zaktualizowany plik `app.py`, w którym kod do tworzenia bazy danych został przeniesiony w odpowiednie miejsce. Wystarczy, że skopiujesz i wkleisz go do swojego pliku `app.py`, a następnie wgrasz na GitHuba.

**Pamiętaj o uzupełnieniu swoich danych w polach `CLIENT_ID`, `CLIENT_SECRET` i `REDIRECT_URI`.**

```python
import os
from flask import Flask, redirect, url_for, request, session, render_template, flash
from flask_sqlalchemy import SQLAlchemy
import requests
import json
import uuid
from datetime import datetime, timedelta

# Inicjalizacja aplikacji i konfiguracja bazy danych
app = Flask(__name__)
# ZMIEŃ TO NA UNIKALNY, LOSOWY KLUCZ!
app.secret_key = 'bardzo_tajny_klucz_sesji'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(app.root_path, 'serwery.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# ZASTĄP TE WARTOŚCI SWOIMI DANYMI Z DISCORD DEVELOPER PORTAL!
CLIENT_ID = "TWÓJ_CLIENT_ID"
CLIENT_SECRET = "TWÓJ_CLIENT_SECRET"
REDIRECT_URI = "http://127.0.0.1:5000/callback"
DISCORD_API_BASE_URL = "https://discord.com/api/v10"

# --- Automatyczne tworzenie bazy danych przy każdym uruchomieniu ---
with app.app_context():
    db.create_all()
    # Dodatkowy kod, aby mieć jeden kod premium na start
    if not PremiumCode.query.filter_by(code='PREMIUM123').first():
        db.session.add(PremiumCode(code='PREMIUM123'))
        db.session.commit()

# --- Modele bazy danych ---

class Server(db.Model):
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=False)
    tags = db.Column(db.String(200))
    invite_link = db.Column(db.String(200))
    icon = db.Column(db.String(200), default='https://via.placeholder.com/60')
    online = db.Column(db.Integer, default=0)
    members = db.Column(db.Integer, default=0)
    is_premium = db.Column(db.Boolean, default=False)
    added_by = db.Column(db.String(100), nullable=False)
    last_bump = db.Column(db.DateTime, default=datetime.now)
    premium_end_date = db.Column(db.DateTime)
    
class PremiumCode(db.Model):
    code = db.Column(db.String(50), primary_key=True)
    server_id = db.Column(db.String(36), db.ForeignKey('server.id'), nullable=True)
    
class Log(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, default=datetime.now)
    message = db.Column(db.Text, nullable=False)

# --- Funkcje pomocnicze ---

def check_and_expire_premium():
    now = datetime.now()
    premium_servers = Server.query.filter(Server.is_premium == True).all()
    
    for server in premium_servers:
        if server.premium_end_date and server.premium_end_date < now:
            server.is_premium = False
            server.premium_end_date = None
            db.session.commit()
            flash(f"Premium dla serwera '{server.name}' wygasło.", 'error')

# --- Ścieżki publiczne (front-end) ---

@app.route('/')
def index():
    check_and_expire_premium()
    query = request.args.get('query', '')
    
    servers_query = Server.query
    if query:
        search_query_lower = f"%{query.lower()}%"
        servers_query = servers_query.filter(
            db.or_(
                Server.name.ilike(search_query_lower),
                Server.tags.ilike(search_query_lower),
                Server.description.ilike(search_query_lower)
            )
        )
    
    servers = servers_query.order_by(
        Server.is_premium.desc(), 
        Server.last_bump.desc()
    ).all()

    # Filtrowanie serwerów użytkownika do wyboru premium
    user_servers = []
    if session.get('user_data'):
        username = session['user_data']['username']
        user_servers = Server.query.filter_by(added_by=username).all()
    
    return render_template(
        'index.html', 
        user=session.get('user_data'), 
        servers=servers, 
        user_servers=user_servers,
        tipply_message="Za wsparcie na Tipply w kwocie minimum 50 zł otrzymasz kod premium na 30 dni. Pamiętaj, aby w opisie donacji podać swój nick z Discorda, żebym mógł Cię dodać i przekazać kod!"
    )

@app.route('/login')
def login():
    return redirect(f"{DISCORD_API_BASE_URL}/oauth2/authorize?client_id={CLIENT_ID}&redirect_uri={REDIRECT_URI}&response_type=code&scope=identify%20guilds")

@app.route('/callback')
def callback():
    code = request.args.get('code')
    if not code:
        return "Błąd: Brak kodu autoryzacyjnego.", 400

    data = {
        'client_id': CLIENT_ID,
        'client_secret': CLIENT_SECRET,
        'grant_type': 'authorization_code',
        'code': code,
        'redirect_uri': REDIRECT_URI,
        'scope': 'identify guilds',
    }
    headers = {'Content-Type': 'application/x-www-form-urlencoded'}
    token_response = requests.post(f"{DISCORD_API_BASE_URL}/oauth2/token", data=data, headers=headers)
    token_data = token_response.json()

    if 'access_token' not in token_data:
        return "Błąd autoryzacji: Nie udało się uzyskać tokena.", 400

    headers = {'Authorization': f"Bearer {token_data['access_token']}"}
    user_response = requests.get(f"{DISCORD_API_BASE_URL}/users/@me", headers=headers)
    user_data = user_response.json()

    session['user_data'] = user_data
    session['token_data'] = token_data
    return redirect(url_for('index'))

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

@app.route('/bump_server/<server_id>', methods=['POST'])
def bump_server(server_id):
    if not session.get('user_data'):
        flash('Musisz być zalogowany, aby podbić serwer.', 'error')
        return redirect(url_for('index'))

    server = Server.query.get(server_id)
    if not server:
        flash('Nie znaleziono takiego serwera.', 'error')
        return redirect(url_for('index'))

    now = datetime.now()
    last_bump = server.last_bump if server.last_bump else datetime.min
    is_premium = server.is_premium
    
    cooldown_seconds = 30 * 60 if is_premium else 3 * 3600
    time_since_last_bump = now - last_bump
    
    if time_since_last_bump.total_seconds() < cooldown_seconds:
        minutes_left = round((cooldown_seconds - time_since_last_bump.total_seconds()) / 60)
        flash(f'Musisz poczekać {minutes_left} minut przed kolejnym podbiciem.', 'error')
        return redirect(url_for('index'))
    
    server.last_bump = now
    db.session.add(Log(message=f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Użytkownik {session['user_data']['username']} podbił serwer '{server.name}'."))
    db.session.commit()
    flash(f'Serwer "{server.name}" został podbity i jest teraz na górze listy!', 'success')
    return redirect(url_for('index'))

@app.route('/activate_premium', methods=['POST'])
def activate_premium():
    code_value = request.form.get('code')
    server_id = request.form.get('server_id')
    
    premium_code = PremiumCode.query.get(code_value)
    if not premium_code:
        flash('Wprowadzono nieprawidłowy kod premium.', 'error')
        return redirect(url_for('index'))
    
    if premium_code.server_id:
        flash('Ten kod premium został już wykorzystany.', 'error')
        return redirect(url_for('index'))
    
    server = Server.query.get(server_id)
    if not server:
        flash('Nie wybrano serwera do aktywacji premium.', 'error')
        return redirect(url_for('index'))

    if not session.get('user_data') or server.added_by != session['user_data']['username']:
        flash('Nie masz uprawnień do aktywacji premium na tym serwerze.', 'error')
        return redirect(url_for('index'))

    server.is_premium = True
    server.premium_end_date = datetime.now() + timedelta(days=30)
    premium_code.server_id = server_id
    db.session.add(Log(message=f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Użytkownik {session.get('user_data', {}).get('username', 'Nieznany')} aktywował kod '{code_value}' na serwerze '{server.name}'."))
    db.session.commit()
    flash('Kod premium został aktywowany pomyślnie!', 'success')
    return redirect(url_for('index'))

@app.route('/add_server_by_user', methods=['POST'])
def add_server_by_user():
    if not session.get('user_data'):
        flash('Musisz być zalogowany, aby dodać serwer.', 'error')
        return redirect(url_for('index'))
    
    name = request.form.get('name')
    description = request.form.get('description')
    tags = request.form.get('tags')
    discord_invite = request.form.get('discord_invite')

    if not discord_invite or not ("discord.gg/" in discord_invite or "discord.com/invite/" in discord_invite):
        flash('Podaj poprawny link do zaproszenia na serwer Discord.', 'error')
        return redirect(url_for('index'))
    
    new_server = Server(
        name=name,
        description=description,
        tags=tags,
        invite_link=discord_invite,
        added_by=session['user_data']['username'],
    )
    db.session.add(new_server)
    db.session.add(Log(message=f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Użytkownik {session['user_data']['username']} dodał serwer '{name}'."))
    db.session.commit()
    flash(f'Twój serwer "{name}" został dodany!', 'success')
    return redirect(url_for('index'))

@app.route('/delete_server_by_user/<server_id>', methods=['POST'])
def delete_server_by_user(server_id):
    if not session.get('user_data'):
        flash('Musisz być zalogowany, aby usunąć serwer.', 'error')
        return redirect(url_for('index'))
        
    server_to_delete = Server.query.get(server_id)
    if not server_to_delete:
        flash('Serwer nie został znaleziony.', 'error')
        return redirect(url_for('index'))
        
    if server_to_delete.added_by != session['user_data']['username']:
        flash('Nie masz uprawnień do usunięcia tego serwera.', 'error')
        return redirect(url_for('index'))

    db.session.delete(server_to_delete)
    db.session.add(Log(message=f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Użytkownik {session['user_data']['username']} usunął serwer '{server_to_delete.name}'."))
    db.session.commit()
    flash(f'Serwer "{server_to_delete.name}" został usunięty.', 'success')
    return redirect(url_for('index'))

# --- Panel admina (dla Ciebie) ---

@app.route('/admin')
def admin_panel():
    servers = Server.query.all()
    premium_codes = PremiumCode.query.all()
    logi = Log.query.order_by(Log.timestamp.desc()).all()
    return render_template('admin.html', servers=servers, premium_codes=premium_codes, logi=logi)

@app.route('/admin/add_server', methods=['POST'])
def add_server():
    name = request.form.get('name')
    description = request.form.get('description')
    tags = request.form.get('tags')
    
    new_server = Server(
        name=name,
        description=description,
        tags=tags,
        added_by="Admin"
    )
    db.session.add(new_server)
    db.session.add(Log(message=f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Admin dodał serwer '{name}'."))
    db.session.commit()
    flash(f'Serwer "{name}" został dodany!', 'success')
    return redirect(url_for('admin_panel'))

@app.route('/admin/add_code', methods=['POST'])
def add_code():
    code_value = request.form.get('code_value')
    new_code = PremiumCode(code=code_value)
    db.session.add(new_code)
    db.session.add(Log(message=f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Admin wygenerował kod premium '{code_value}'."))
    db.session.commit()
    flash(f'Kod premium "{code_value}" został dodany!', 'success')
    return redirect(url_for('admin_panel'))

@app.route('/admin/delete_server/<server_id>', methods=['POST'])
def delete_server(server_id):
    server = Server.query.get(server_id)
    if server:
        db.session.delete(server)
        db.session.add(Log(message=f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Admin usunął serwer '{server.name}'."))
        db.session.commit()
        flash('Serwer został usunięty.', 'success')
    return redirect(url_for('admin_panel'))

if __name__ == '__main__':
    app.run(debug=True, port=5000)
```