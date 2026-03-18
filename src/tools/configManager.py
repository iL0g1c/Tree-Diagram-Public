import yaml
import os
from pathlib import Path

class ConfigManager:
    def __init__(self):
        self.config_path = Path(__file__).resolve().parents[2] / "config.yaml"
    
    def load_config(self):
        if not os.path.exists(self.config_path):
            raise FileNotFoundError(f"Config file not found at {self.config_path}")
            
        with open(self.config_path, 'r') as file:
            return yaml.safe_load(file)
        
    