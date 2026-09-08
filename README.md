# TaskManager

CLI + GUI task manager with JSON storage and Kanban board.

## Features

- **CLI**: Add, list, update, delete, search, stats, clear.
- **GUI**: Kanban board (To Do / In Progress / Done / Archived), drag-free moves, edit, delete, notifications.
- Priorities, statuses, categories, tags, due dates, effort, dependencies.
- JSON storage with automatic backups.

## Requirements

- Python 3.6+ (tkinter included, optional: `pillow`, `plyer`)

## Installation


git clone https://github.com/yourusername/taskmanager.git
cd taskmanager
pip install pillow plyer  # optional
chmod +x task_manager.py
Usage
GUI (default)
bash
python task_manager.py        # or: python task_manager.py gui
CLI Examples
bash
# Add task
python task_manager.py add "Finish report" -p high -c Work --due "2026-09-15 17:00"

# List tasks
python task_manager.py list --status pending --search "report"

# Update task
python task_manager.py update 1234 --status completed

# Delete
python task_manager.py delete 1234

# Statistics
python task_manager.py stats

# Clear all
python task_manager.py clear --force
Data Storage
tasks.json – main storage.

tasks.json.backup – automatic backup.

config.json – GUI settings.

Troubleshooting
Use latest version – canvas tags now prefixed with "task_" to avoid ID conflicts.

Status strings are normalised (spaces → underscores) – works with "In Progress".

License
MIT
