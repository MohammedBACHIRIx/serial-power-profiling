import sys
import os

repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if repo_root not in sys.path:
    sys.path.insert(0, repo_root)

from powerprofiler import logger_app

if __name__ == "__main__":
    config_path = os.path.join(repo_root, "config", "devices.json")
    if not os.path.exists(config_path):
        config_path = os.path.join(repo_root, "config", "devices.example.json")
    sys.argv = [sys.argv[0], "--config", config_path]
    logger_app.main()
