import os
from dotenv import load_dotenv

from flask import Flask, send_from_directory, jsonify
from flask_cors import CORS
from extensions import db
from flask_login import LoginManager, AnonymousUserMixin
from werkzeug.security import generate_password_hash
from models import User
import io
import csv
import logging

logging.basicConfig(level=logging.INFO)
print("🚀 Aenigma starting...")

load_dotenv()

# Lazy imports for fast startup
frag_caesar_client = None


def get_frag_caesar():
    """Lazy import frag_caesar_bs4 - avoids startup timeout."""
    global frag_caesar_client
    if frag_caesar_client is None:
        import frag_caesar_bs4
        frag_caesar_client = frag_caesar_bs4
    return frag_caesar_client


def create_app():
    """
    Factory function to create and configure the Flask application.
    Optimized for Render/Neon: Fast startup, lazy imports, conditional DB init.
    """
    # Import blueprints after load_dotenv
    from routes.vocab import vocab_bp
    from routes.quiz import quiz_bp
    from routes.cards import cards_bp
    from routes.auth import auth_bp

    app = Flask(__name__)

    # Neon Postgres / SQLite
    db_url = os.getenv('DATABASE_URL')
    if db_url and db_url.startswith('postgres://'):
        db_url = db_url.replace('postgres://', 'postgresql://')
    app.config["SQLALCHEMY_DATABASE_URI"] = db_url or "sqlite:///latin_vocab.db"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "fallback-secret-key")

    # AI config (safe init)
    try:
        from openai import OpenAI
        api_key = os.getenv("OPENAI_API_KEY")
        app.config['client'] = OpenAI(api_key=api_key) if api_key else None
    except Exception as e:
        print(f"OpenAI init skipped: {e}")
        app.config['client'] = None

    # Register blueprints
    app.register_blueprint(auth_bp, url_prefix='/api/auth')
    app.register_blueprint(vocab_bp, url_prefix='/api/vocab')
    app.register_blueprint(quiz_bp, url_prefix='/api/quiz')
    app.register_blueprint(cards_bp, url_prefix='/api/cards')

    # Extensions
    db.init_app(app)
    CORS(app)

    # Flask-Login
    login_manager = LoginManager()
    login_manager.init_app(app)
    login_manager.anonymous_user = AnonymousUserMixin

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    # FAST STARTUP: Skip heavy init on Render
    with app.app_context():
        # Always create tables safely (idempotent)
        db.create_all()

        # Local demo only
        if not os.getenv('DATABASE_URL'):
            _create_demo_user_if_missing()
        else:
            print("🛡️ Production: Tables created, Neon handles data")
    return app


def _create_demo_user_if_missing():
    """Create demo user only LOCAL (skip Render/Neon)."""
    if os.getenv('DATABASE_URL') or os.getenv('RENDER') == 'true':
        print("🛡️ Production: Skip demo user")
        return

    demo_user = User.query.filter_by(username='demo').first()
    if not demo_user:
        demo_user = User(username='demo', password_hash=generate_password_hash('demo'))
        db.session.add(demo_user)
        db.session.commit()
        print("✅ Demo user created")


# Create app
app = create_app()


@app.route("/")
def index():
    """Serve frontend."""
    return send_from_directory("static", "index.html")


@app.route('/api/kurzuebersicht/<word>')
def api_kurzuebersicht(word):
    """Frag-Caesar Kurzübersicht → JSON (lazy import)."""
    try:
        client = get_frag_caesar()
        raw_tsv = client.get_kurzuebersicht(word)

        if not raw_tsv or raw_tsv.strip() == '':
            return jsonify([])

        # TSV → JSON (skip header)
        reader = csv.DictReader(io.StringIO(raw_tsv), delimiter='\t')
        data = [row for row in reader]

        # Add 'latin' if missing
        for row in data:
            if not row.get('Latein'):
                row['Latein'] = word

        return jsonify(data)
    except Exception as e:
        print(f"Kurzübersicht error: {e}")
        return jsonify([])


if __name__ == "__main__":
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)  # ← Render bind!

