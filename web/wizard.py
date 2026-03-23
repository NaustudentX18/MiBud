"""
MiBud - Setup Wizard
Web-based initial configuration wizard
"""

import asyncio
import logging
from pathlib import Path
from typing import Optional

log = logging.getLogger("MiBud")


class SetupWizard:
    """Handles first-run setup wizard"""
    
    def __init__(self, config, event_bus):
        self.config = config
        self.event_bus = event_bus
        self.is_running = False
        self._server = None
        
    async def run(self):
        """Launch the setup wizard"""
        log.info("📝 Starting setup wizard...")
        self.is_running = True
        
        try:
            from flask import Flask, render_template, request, jsonify, redirect, url_for
            app = Flask(__name__, template_folder='templates')
            
            @app.route('/')
            def index():
                return render_template('wizard.html')
                
            @app.route('/api/config', methods=['GET'])
            def get_config():
                return jsonify(self.config.data)
                
            @app.route('/api/config', methods=['POST'])
            def save_config():
                data = request.json
                for key, value in data.items():
                    self.config.set(key, value)
                self.config.save()
                self.config.mark_setup_complete()
                return jsonify({"status": "ok"})
                
            @app.route('/api/complete', methods=['POST'])
            def complete():
                self.is_running = False
                return jsonify({"status": "ok"})
                
            log.info("📝 Setup wizard running at http://mibud.local:5000")
            
            app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)
            
        except Exception as e:
            log.error(f"Setup wizard error: {e}")
            self.is_running = False
            raise
            
    async def stop(self):
        """Stop the wizard"""
        self.is_running = False
        log.info("📝 Setup wizard stopped")
