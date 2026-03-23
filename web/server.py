"""
MiBud Web Server
Flask-based web interface for setup wizard and dashboard
"""

import os
import logging
from pathlib import Path
from flask import Flask, render_template, request, jsonify, redirect, url_for
import asyncio

log = logging.getLogger("MiBud")

# Create Flask app
app = Flask(__name__, 
            template_folder='templates',
            static_folder='static')
app.secret_key = os.urandom(24)

# ── Routes ─────────────────────────────────────────────────────

@app.route('/')
def index():
    """Main page - redirects to wizard or dashboard"""
    # Check if setup is complete
    config_path = Path(__file__).parent.parent / "config" / "config.json"
    if config_path.exists():
        import json
        with open(config_path) as f:
            config = json.load(f)
            if config.get("setup_complete", False):
                return redirect(url_for('dashboard'))
    return redirect(url_for('wizard'))


@app.route('/wizard')
def wizard():
    """Setup wizard page"""
    return render_template('wizard.html')


@app.route('/dashboard')
def dashboard():
    """Main dashboard"""
    return render_template('dashboard.html')


@app.route('/api/status')
def api_status():
    """Get MiBud status"""
    return jsonify({
        "status": "running",
        "personality": "assistant",
        "battery": 85,
        "wifi": 4,
        "online": True,
        "version": "0.1.0"
    })


@app.route('/api/config')
def api_config():
    """Get configuration"""
    config_path = Path(__file__).parent.parent / "config" / "config.json"
    if config_path.exists():
        import json
        with open(config_path) as f:
            return jsonify(json.load(f))
    return jsonify({})


@app.route('/api/config/save', methods=['POST'])
def api_config_save():
    """Save configuration"""
    try:
        data = request.json
        config_path = Path(__file__).parent.parent / "config" / "config.json"
        config_path.parent.mkdir(parents=True, exist_ok=True)
        
        import json
        with open(config_path, 'w') as f:
            json.dump(data, f, indent=2)
            
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route('/api/personality/list')
def api_personality_list():
    """Get available personalities"""
    from personalities import get_all_personalities
    personalities = get_all_personalities()
    return jsonify([
        {
            "id": p.id,
            "name": p.name,
            "description": p.description,
            "emoji": p.emoji,
            "specialty": p.specialty
        }
        for p in personalities
    ])


@app.route('/api/personality/set', methods=['POST'])
def api_personality_set():
    """Set current personality"""
    data = request.json
    personality = data.get('personality')
    
    if personality:
        config_path = Path(__file__).parent.parent / "config" / "config.json"
        import json
        with open(config_path) as f:
            config = json.load(f)
        config['personality']['current'] = personality
        with open(config_path, 'w') as f:
            json.dump(config, f, indent=2)
            
        return jsonify({"success": True})
    
    return jsonify({"success": False, "error": "No personality specified"})


@app.route('/api/personality/create', methods=['POST'])
def api_personality_create():
    """Create a new custom personality"""
    try:
        from personalities.manager import PersonalityManager
        manager = PersonalityManager()
        personality = manager.create_personality(request.json)
        return jsonify({"success": True, "personality": {
            "id": personality.id,
            "name": personality.name,
            "description": personality.description,
            "emoji": personality.emoji
        }})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route('/api/personality/<personality_id>')
def api_personality_get(personality_id):
    """Get personality details"""
    from personalities.manager import PersonalityManager
    manager = PersonalityManager()
    details = manager.get_personality_details(personality_id)
    if details:
        return jsonify(details)
    return jsonify({"error": "Personality not found"}), 404


@app.route('/api/personality/<personality_id>', methods=['PUT'])
def api_personality_update(personality_id):
    """Update a custom personality"""
    try:
        from personalities.manager import PersonalityManager
        manager = PersonalityManager()
        personality = manager.update_personality(personality_id, request.json)
        if personality:
            return jsonify({"success": True})
        return jsonify({"success": False, "error": "Custom personality not found"}), 404
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route('/api/personality/<personality_id>', methods=['DELETE'])
def api_personality_delete(personality_id):
    """Delete a custom personality"""
    from personalities.manager import PersonalityManager
    manager = PersonalityManager()
    if manager.delete_personality(personality_id):
        return jsonify({"success": True})
    return jsonify({"success": False, "error": "Personality not found or is a preset"}), 404


@app.route('/api/providers')
def api_providers():
    """Get available AI providers"""
    return jsonify([
        {"id": "openrouter", "name": "OpenRouter (Free)", "models": ["gemini-2.0-flash-lite:free"]},
        {"id": "openai", "name": "OpenAI", "models": ["gpt-4o", "gpt-4o-mini"]},
        {"id": "anthropic", "name": "Anthropic Claude", "models": ["claude-3-5-sonnet"]},
        {"id": "google", "name": "Google Gemini", "models": ["gemini-2.0-flash"]},
        {"id": "deepseek", "name": "DeepSeek", "models": ["deepseek-chat"]},
        {"id": "ollama", "name": "Ollama (Offline)", "models": ["phi3", "tinyllama", "mistral"]},
    ])


@app.route('/api/keys/save', methods=['POST'])
def api_keys_save():
    """Save API keys"""
    data = request.json
    keys = data.get('keys', {})
    
    config_path = Path(__file__).parent.parent / "config" / "config.json"
    import json
    with open(config_path) as f:
        config = json.load(f)
    
    config['api_keys'] = keys
    config['first_run'] = False
    config['setup_complete'] = True
    
    with open(config_path, 'w') as f:
        json.dump(config, f, indent=2)
    
    return jsonify({"success": True})


# ── Wizard Steps ──────────────────────────────────────────────

@app.route('/wizard/step/<int:step>')
def wizard_step(step):
    """Get wizard step content"""
    steps = {
        1: {"title": "Welcome", "description": "Welcome to MiBud setup!"},
        2: {"title": "Hardware", "description": "Detecting hardware..."},
        3: {"title": "Audio", "description": "Testing audio..."},
        4: {"title": "WiFi", "description": "Connecting to network..."},
        5: {"title": "AI Provider", "description": "Choose your AI provider..."},
        6: {"title": "API Keys", "description": "Enter your API keys..."},
        7: {"title": "Personality", "description": "Choose your MiBud personality..."},
        8: {"title": "Complete", "description": "Setup complete!"},
    }
    
    if step in steps:
        return jsonify(steps[step])
    return jsonify({"error": "Invalid step"})


# ── Main ───────────────────────────────────────────────────────

def run_server(host='0.0.0.0', port=5000):
    """Run the web server"""
    log.info(f"🌐 Starting web server at http://{host}:{port}")
    app.run(host=host, port=port, debug=False, threaded=True)


if __name__ == '__main__':
    run_server()
