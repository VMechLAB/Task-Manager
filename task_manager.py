#!/usr/bin/env python3
"""
Task Manager - Full Application (Fixed)
Combines CLI and GUI with persistent JSON storage.
"""

import json
import os
import sys
import hashlib
import shutil
import argparse
from datetime import datetime
from enum import Enum
from typing import List, Dict, Optional, Any

# GUI imports
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext

# Optional imports
try:
    from PIL import Image, ImageTk, ImageDraw
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

try:
    from plyer import notification
    HAS_PLYER = True
except ImportError:
    HAS_PLYER = False


# ================ CORE BACKEND ================
class Priority(Enum):
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    URGENT = 4

    @classmethod
    def from_string(cls, value: str) -> "Priority":
        mapping = {
            'low': Priority.LOW,
            'medium': Priority.MEDIUM,
            'high': Priority.HIGH,
            'urgent': Priority.URGENT
        }
        return mapping.get(value.lower(), Priority.MEDIUM)

    def __str__(self):
        return self.name.title()


class TaskStatus(Enum):
    PENDING = 'pending'
    IN_PROGRESS = 'in_progress'
    COMPLETED = 'completed'
    ARCHIVED = 'archived'

    @classmethod
    def from_string(cls, value: str) -> "TaskStatus":
        # Normalize: replace spaces with underscores, lower
        key = value.lower().replace(' ', '_')
        mapping = {
            'pending': TaskStatus.PENDING,
            'in_progress': TaskStatus.IN_PROGRESS,
            'completed': TaskStatus.COMPLETED,
            'archived': TaskStatus.ARCHIVED
        }
        return mapping.get(key, TaskStatus.PENDING)

    def __str__(self):
        return self.value.replace('_', ' ').title()


class Task:
    def __init__(
        self,
        title: str,
        description: str = '',
        priority: Priority = Priority.MEDIUM,
        status: TaskStatus = TaskStatus.PENDING,
        category: str = 'General',
        due_date: Optional[datetime] = None,
        tags: Optional[List[str]] = None,
        effort: int = 0,
        dependencies: Optional[List[str]] = None,
        task_id: Optional[str] = None
    ):
        self.title = title
        self.description = description
        self.priority = priority
        self.status = status
        self.category = category
        self.due_date = due_date
        self.tags = tags or []
        self.effort = effort
        self.dependencies = dependencies or []
        self.created_at = datetime.now()
        self.updated_at = datetime.now()
        self.task_id = task_id or self._generate_id()

    def _generate_id(self) -> str:
        content = f"{self.title}{self.created_at.isoformat()}"
        return hashlib.md5(content.encode()).hexdigest()[:8]

    def to_dict(self) -> Dict[str, Any]:
        return {
            'task_id': self.task_id,
            'title': self.title,
            'description': self.description,
            'priority': self.priority.value,
            'status': self.status.value,
            'category': self.category,
            'due_date': self.due_date.isoformat() if self.due_date else None,
            'tags': self.tags,
            'effort': self.effort,
            'dependencies': self.dependencies,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat()
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Task":
        task = cls(
            title=data['title'],
            description=data.get('description', ''),
            priority=Priority(data.get('priority', 2)),
            status=TaskStatus.from_string(data.get('status', 'pending')),
            category=data.get('category', 'General'),
            due_date=datetime.fromisoformat(data['due_date']) if data.get('due_date') else None,
            tags=data.get('tags', []),
            effort=data.get('effort', 0),
            dependencies=data.get('dependencies', []),
            task_id=data.get('task_id')
        )
        task.created_at = datetime.fromisoformat(data['created_at'])
        task.updated_at = datetime.fromisoformat(data['updated_at'])
        return task

    def update(self, **kwargs) -> None:
        for key, value in kwargs.items():
            if hasattr(self, key):
                setattr(self, key, value)
        self.updated_at = datetime.now()

    def is_overdue(self) -> bool:
        if not self.due_date or self.status == TaskStatus.COMPLETED:
            return False
        return datetime.now() > self.due_date

    def is_blocked(self, manager: "TaskManager") -> bool:
        for dep_id in self.dependencies:
            dep = manager.get_task(dep_id)
            if dep and dep.status != TaskStatus.COMPLETED:
                return True
        return False

    def __str__(self) -> str:
        due_str = f"Due: {self.due_date.strftime('%Y-%m-%d %H:%M')}" if self.due_date else "No due date"
        return f"[{self.task_id}] {self.title} ({self.priority}) - {self.status}\n  {due_str} | Category: {self.category}"


class TaskManager:
    def __init__(self, storage_file: str = 'tasks.json'):
        self.storage_file = storage_file
        self.backup_file = storage_file + '.backup'
        self.tasks: Dict[str, Task] = {}
        self.load_tasks()

    def add_task(self, task: Task) -> str:
        self.tasks[task.task_id] = task
        self.save_tasks()
        return task.task_id

    def get_task(self, task_id: str) -> Optional[Task]:
        return self.tasks.get(task_id)

    def update_task(self, task_id: str, **kwargs) -> bool:
        task = self.get_task(task_id)
        if not task:
            return False
        task.update(**kwargs)
        self.save_tasks()
        return True

    def delete_task(self, task_id: str) -> bool:
        if task_id in self.tasks:
            for t in self.tasks.values():
                if task_id in t.dependencies:
                    t.dependencies.remove(task_id)
            del self.tasks[task_id]
            self.save_tasks()
            return True
        return False

    def delete_tasks(self, task_ids: List[str]) -> None:
        for tid in task_ids:
            self.delete_task(tid)

    def list_tasks(
        self,
        status: Optional[TaskStatus] = None,
        category: Optional[str] = None,
        priority: Optional[Priority] = None,
        search: Optional[str] = None
    ) -> List[Task]:
        filtered = list(self.tasks.values())

        if status:
            filtered = [t for t in filtered if t.status == status]
        if category:
            filtered = [t for t in filtered if t.category.lower() == category.lower()]
        if priority:
            filtered = [t for t in filtered if t.priority == priority]
        if search:
            search_lower = search.lower()
            filtered = [
                t for t in filtered
                if search_lower in t.title.lower()
                or search_lower in t.description.lower()
                or any(search_lower in tag.lower() for tag in t.tags)
            ]

        filtered.sort(key=lambda t: (t.due_date or datetime.max, -t.priority.value))
        return filtered

    def get_overdue_tasks(self) -> List[Task]:
        return [t for t in self.tasks.values() if t.is_overdue()]

    def get_statistics(self) -> Dict[str, Any]:
        total = len(self.tasks)
        completed = sum(1 for t in self.tasks.values() if t.status == TaskStatus.COMPLETED)
        pending = sum(1 for t in self.tasks.values() if t.status == TaskStatus.PENDING)
        in_progress = sum(1 for t in self.tasks.values() if t.status == TaskStatus.IN_PROGRESS)
        archived = sum(1 for t in self.tasks.values() if t.status == TaskStatus.ARCHIVED)
        overdue = len(self.get_overdue_tasks())

        categories = {}
        for task in self.tasks.values():
            categories[task.category] = categories.get(task.category, 0) + 1

        return {
            'total': total,
            'completed': completed,
            'pending': pending,
            'in_progress': in_progress,
            'archived': archived,
            'overdue': overdue,
            'completion_rate': (completed / total * 100) if total > 0 else 0,
            'categories': categories
        }

    def save_tasks(self) -> None:
        if os.path.exists(self.storage_file):
            shutil.copy2(self.storage_file, self.backup_file)

        data = {
            'tasks': [task.to_dict() for task in self.tasks.values()],
            'last_updated': datetime.now().isoformat()
        }
        try:
            with open(self.storage_file, 'w') as f:
                json.dump(data, f, indent=2)
        except IOError as e:
            print(f"Error saving tasks: {e}", file=sys.stderr)

    def load_tasks(self) -> None:
        if not os.path.exists(self.storage_file):
            return

        try:
            with open(self.storage_file, 'r') as f:
                data = json.load(f)

            for task_data in data.get('tasks', []):
                task = Task.from_dict(task_data)
                self.tasks[task.task_id] = task
        except (IOError, json.JSONDecodeError, KeyError) as e:
            print(f"Error loading tasks: {e}", file=sys.stderr)
            if os.path.exists(self.backup_file):
                try:
                    with open(self.backup_file, 'r') as f:
                        data = json.load(f)
                    for task_data in data.get('tasks', []):
                        task = Task.from_dict(task_data)
                        self.tasks[task.task_id] = task
                    print("Recovered from backup.")
                except:
                    self.tasks = {}
            else:
                self.tasks = {}


# ================ GUI FRONTEND ================
class KanbanGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Task Manager")
        self.root.geometry("1400x800")
        self.root.minsize(1200, 600)

        self.manager = TaskManager()
        self.load_config()
        self.setup_theme()

        self.canvas = tk.Canvas(self.root, highlightthickness=0, bg=self.bg_color)
        self.canvas.pack(fill='both', expand=True)

        self.root.update_idletasks()

        self.load_background()
        self.create_header()
        self.create_columns()

        self.task_id_map = {}
        self._card_images = {}

        self.refresh_kanban()
        self.check_overdue_notifications()

        self.root.bind('<Control-n>', lambda e: self.add_task_dialog())
        self.root.bind('<Control-d>', lambda e: self.bulk_delete())
        self.root.bind('<Configure>', self.on_resize)

        style = ttk.Style()
        style.configure('Accent.TButton', background='#4f46e5', foreground='white')
        style.configure('Danger.TButton', background='#ef4444', foreground='white')

    def load_config(self):
        self.config_file = "config.json"
        self.config = {}
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r') as f:
                    self.config = json.load(f)
            except:
                pass
        self.config.setdefault('background', 'mybackground.jpg')
        self.config.setdefault('theme', 'light')

    def save_config(self):
        try:
            with open(self.config_file, 'w') as f:
                json.dump(self.config, f, indent=2)
        except:
            pass

    def setup_theme(self):
        self.bg_color = '#f0f2f5'
        self.fg_color = '#1e293b'
        self.accent = '#4f46e5'
        self.light_accent = '#eef2ff'
        self.card_bg = '#ffffff'
        self.card_shadow = '#cbd5e1'

        import tkinter.font as tkfont
        preferred_fonts = [
            "Yu Gothic", "Meiryo", "Noto Sans JP",
            "MS Gothic", "KaiTi", "SimHei",
            "Arial", "Helvetica"
        ]
        self.font_family = "Helvetica"
        for f in preferred_fonts:
            try:
                tkfont.Font(family=f, size=10)
                self.font_family = f
                break
            except:
                continue

        self.title_font = (self.font_family, 20, 'bold')
        self.header_font = (self.font_family, 12, 'bold')
        self.card_font = (self.font_family, 10)
        self.small_font = (self.font_family, 9)

    def load_background(self):
        self.canvas.delete('bg')
        bg_path = self.config.get('background', 'mybackground.jpg')
        if os.path.exists(bg_path) and HAS_PIL:
            try:
                img = Image.open(bg_path)
                w = self.root.winfo_width()
                h = self.root.winfo_height()
                if w < 10: w = 1400
                if h < 10: h = 800
                img = img.resize((w, h), Image.LANCZOS)
                self.bg_image = ImageTk.PhotoImage(img)
                self.canvas.create_image(0, 0, image=self.bg_image, anchor='nw', tags='bg')
                self.canvas.tag_lower('bg')
            except Exception as e:
                print(f"Could not load background: {e}")
                self.canvas.configure(bg='#1e293b')
        else:
            self.canvas.configure(bg='#1e293b')

    def on_resize(self, event):
        if hasattr(self, 'bg_image'):
            self.load_background()
            self.create_columns()
            self.refresh_kanban()

    def create_header(self):
        self.canvas.delete('header')
        header_y = 20
        self.canvas.create_text(30, header_y, text="Tasks", anchor='w',
                                font=self.title_font, fill='white', tags='header')

        btn_data = [
            ("Add Task", self.add_task_dialog, '#4f46e5'),
            ("Delete Selected", self.bulk_delete, '#ef4444'),
            ("Statistics", self.show_stats, '#4f46e5'),
            ("Refresh", self.refresh_kanban, '#6b7280')
        ]
        canvas_width = self.root.winfo_width()
        if canvas_width < 100:
            canvas_width = 1400
        x = canvas_width - 20
        for text, cmd, color in btn_data:
            btn_width = len(text) * 8 + 20
            btn_x = x - btn_width - 10
            rect_id = self.canvas.create_rectangle(btn_x, header_y-8, x, header_y+28,
                                                   fill=color, outline='', tags='header')
            text_id = self.canvas.create_text((btn_x + x)//2, header_y+10, text=text,
                                              font=self.header_font, fill='white', tags='header')
            self.canvas.tag_bind(rect_id, '<Button-1>', lambda e, cmd=cmd: cmd())
            self.canvas.tag_bind(text_id, '<Button-1>', lambda e, cmd=cmd: cmd())
            x = btn_x - 10

        canvas_height = self.root.winfo_height()
        if canvas_height < 100:
            canvas_height = 800
        self.status_text = self.canvas.create_text(20, canvas_height-20,
                                                   anchor='sw', font=self.small_font,
                                                   fill='white', tags='status')
        self.update_status()

    def create_columns(self):
        self.canvas.delete('column')
        self.canvas.delete('card')

        column_config = [
            ('To Do', TaskStatus.PENDING),
            ('In Progress', TaskStatus.IN_PROGRESS),
            ('Done', TaskStatus.COMPLETED),
            ('Archived', TaskStatus.ARCHIVED)
        ]

        canvas_width = self.root.winfo_width()
        if canvas_width < 100:
            canvas_width = 1400
        col_width = (canvas_width - 100) // 4
        x_positions = [40 + i * (col_width + 10) for i in range(4)]

        self.column_data = {}

        for (name, status), x in zip(column_config, x_positions):
            col_bg = self.create_semi_transparent_rect(col_width - 10, 500, alpha=200, color='white')
            bg_id = self.canvas.create_image(x+5, 70, image=col_bg, anchor='nw', tags='column')
            title_id = self.canvas.create_text(x+col_width//2, 60, text=name,
                                               font=self.header_font, fill='#1e293b', tags='column')

            self.column_data[status] = {
                'x': x,
                'width': col_width - 10,
                'y_start': 90,
                'card_ids': [],
                'task_ids': [],
                'bg_id': bg_id,
                'title_id': title_id,
            }

    def create_semi_transparent_rect(self, width, height, alpha=180, color='white'):
        if not HAS_PIL:
            img = tk.PhotoImage(width=width, height=height)
            img.put(color, to=(0, 0, width, height))
            return img
        img = Image.new('RGBA', (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.rectangle((0, 0, width, height), fill=(255, 255, 255, alpha))
        return ImageTk.PhotoImage(img)

    def refresh_kanban(self):
        """Redraw all task cards using prefixed tags."""
        self.canvas.delete('card')
        self.task_id_map.clear()
        self._card_images.clear()

        if not hasattr(self, 'column_data') or not self.column_data:
            self.create_columns()

        for status, col in self.column_data.items():
            tasks = self.manager.list_tasks(status=status)
            y = col['y_start']
            self.task_id_map[status] = []
            col['card_ids'] = []
            col['task_ids'] = []

            for task in tasks:
                card_id = self.create_task_card(task, col['x']+5, y, col['width'])
                self.task_id_map[status].append(task.task_id)
                col['card_ids'].append(card_id)
                col['task_ids'].append(task.task_id)
                y += 110

        self.update_status()

    def create_task_card(self, task, x, y, width):
        """Draw a single task card with prefixed tags."""
        card_bg = self.create_semi_transparent_rect(width, 100, alpha=200, color='white')
        bg_id = self.canvas.create_image(x, y, image=card_bg, anchor='nw',
                                         tags=('card', f"task_{task.task_id}"))
        self._card_images[task.task_id] = card_bg

        priority_colors = {
            Priority.LOW: '#22c55e',
            Priority.MEDIUM: '#eab308',
            Priority.HIGH: '#f97316',
            Priority.URGENT: '#ef4444'
        }
        p_color = priority_colors.get(task.priority, "#020202")
        self.canvas.create_rectangle(x+2, y+2, x+6, y+98, fill=p_color, outline='',
                                     tags=('card', f"task_{task.task_id}"))

        title = task.title[:30] + '…' if len(task.title) > 30 else task.title
        self.canvas.create_text(x+20, y+15, text=title, anchor='w',
                                font=self.card_font, fill='#1e293b',
                                tags=('card', f"task_{task.task_id}"))

        tags_str = ', '.join(task.tags) if task.tags else ''
        effort_str = self.format_effort(task.effort) if task.effort else ''
        info = f"{tags_str} {effort_str}".strip()
        self.canvas.create_text(x+20, y+40, text=info, anchor='w',
                                font=self.small_font, fill='#64748b',
                                tags=('card', f"task_{task.task_id}"))

        if task.due_date:
            due_str = task.due_date.strftime('%d/%m %H:%M')
            overdue = task.is_overdue()
            color = '#ef4444' if overdue else '#64748b'
            self.canvas.create_text(x+20, y+60, text=f"due {due_str}", anchor='w',
                                    font=self.small_font, fill=color,
                                    tags=('card', f"task_{task.task_id}"))

        tag = f"task_{task.task_id}"
        self.canvas.tag_bind(tag, '<Button-1>',
                             lambda e, tid=task.task_id: self.select_task(tid))
        self.canvas.tag_bind(tag, '<Double-Button-1>',
                             lambda e, tid=task.task_id: self.edit_task_dialog(tid, None, False))
        self.canvas.tag_bind(tag, '<Button-3>',
                             lambda e, tid=task.task_id: self.show_card_context(e, tid))

        return bg_id

    def format_effort(self, minutes):
        if minutes < 60:
            return f"{minutes}m"
        h = minutes // 60
        m = minutes % 60
        return f"{h}h {m}m" if m else f"{h}h"

    def select_task(self, task_id):
        self.selected_task_id = task_id

    def show_card_context(self, event, task_id):
        menu = tk.Menu(self.root, tearoff=0, bg="#ffffff", fg='#1e293b')
        menu.add_command(label="Edit", command=lambda: self.edit_task_dialog(task_id, None, False))
        menu.add_command(label="Delete", command=lambda: self.delete_task(task_id))
        menu.add_separator()
        task = self.manager.get_task(task_id)
        if task:
            for s in TaskStatus:
                if s != task.status:
                    menu.add_command(label=f"Move to {str(s)}", command=lambda s=s: self.move_task(task_id, s))
        menu.post(event.x_root, event.y_root)

    def add_task_dialog(self):
        self.edit_task_dialog(None, None, True)

    def edit_task_dialog(self, task_id=None, status=None, is_new=False):
        if is_new:
            task = Task(title="", status=TaskStatus.PENDING)
        else:
            task = self.manager.get_task(task_id)
            if not task:
                return

        dialog = tk.Toplevel(self.root)
        dialog.title("Add Task" if is_new else "Edit Task")
        dialog.geometry("550x700")
        dialog.configure(bg='#f0f2f5')
        dialog.transient(self.root)
        dialog.grab_set()

        try:
            dialog.attributes('-alpha', 0.95)
        except:
            pass

        main = ttk.Frame(dialog)
        main.pack(fill='both', expand=True, padx=20, pady=20)

        label_font = self.header_font
        entry_font = self.card_font

        ttk.Label(main, text="Title *", font=label_font).grid(row=0, column=0, sticky='w', pady=(0,5))
        title_entry = ttk.Entry(main, width=50, font=entry_font)
        title_entry.grid(row=1, column=0, columnspan=2, sticky='ew', pady=(0,10))
        if not is_new:
            title_entry.insert(0, task.title)

        ttk.Label(main, text="Description", font=label_font).grid(row=2, column=0, sticky='w', pady=(0,5))
        desc_text = scrolledtext.ScrolledText(main, height=4, font=entry_font,
                                              bg='white', fg='black')
        desc_text.grid(row=3, column=0, columnspan=2, sticky='ew', pady=(0,10))
        if not is_new:
            desc_text.insert('1.0', task.description)

        ttk.Label(main, text="Priority", font=label_font).grid(row=4, column=0, sticky='w', pady=(0,5))
        priority_var = tk.StringVar(value=task.priority.name.title())
        p_frame = ttk.Frame(main)
        p_frame.grid(row=5, column=0, columnspan=2, sticky='w', pady=(0,10))
        for i, p in enumerate(['Low', 'Medium', 'High', 'Urgent']):
            rb = ttk.Radiobutton(p_frame, text=p, variable=priority_var, value=p)
            rb.grid(row=0, column=i, padx=10)

        ttk.Label(main, text="Category", font=label_font).grid(row=6, column=0, sticky='w', pady=(0,5))
        cat_entry = ttk.Entry(main, width=30, font=entry_font)
        cat_entry.grid(row=7, column=0, columnspan=2, sticky='w', pady=(0,10))
        if not is_new:
            cat_entry.insert(0, task.category)

        ttk.Label(main, text="Tags (comma-separated)", font=label_font).grid(row=8, column=0, sticky='w', pady=(0,5))
        tags_entry = ttk.Entry(main, width=50, font=entry_font)
        tags_entry.grid(row=9, column=0, columnspan=2, sticky='ew', pady=(0,10))
        if not is_new:
            tags_entry.insert(0, ', '.join(task.tags))

        ttk.Label(main, text="Effort (minutes)", font=label_font).grid(row=10, column=0, sticky='w', pady=(0,5))
        effort_entry = ttk.Entry(main, width=10, font=entry_font)
        effort_entry.grid(row=11, column=0, sticky='w', pady=(0,10))
        if not is_new and task.effort:
            effort_entry.insert(0, str(task.effort))

        ttk.Label(main, text="Due Date (YYYY-MM-DD HH:MM)", font=label_font).grid(row=12, column=0, sticky='w', pady=(0,5))
        due_entry = ttk.Entry(main, width=25, font=entry_font)
        due_entry.grid(row=13, column=0, sticky='w', pady=(0,10))
        if not is_new and task.due_date:
            due_entry.insert(0, task.due_date.strftime('%Y-%m-%d %H:%M'))

        ttk.Label(main, text="Dependencies (select from list)", font=label_font).grid(row=14, column=0, sticky='w', pady=(0,5))
        dep_frame = ttk.Frame(main)
        dep_frame.grid(row=15, column=0, columnspan=2, sticky='ew', pady=(0,10))

        dep_listbox = tk.Listbox(dep_frame, selectmode='multiple', height=4,
                                 bg='white', fg='black', selectbackground=self.accent)
        dep_listbox.pack(side='left', fill='x', expand=True)
        dep_scroll = ttk.Scrollbar(dep_frame, orient='vertical', command=dep_listbox.yview)
        dep_scroll.pack(side='right', fill='y')
        dep_listbox.config(yscrollcommand=dep_scroll.set)

        all_tasks = self.manager.list_tasks()
        current_deps = set(task.dependencies)
        dep_id_to_index = {}
        for i, t in enumerate(all_tasks):
            dep_listbox.insert(tk.END, f"{t.task_id[:6]} - {t.title}")
            dep_id_to_index[t.task_id] = i
            if t.task_id in current_deps:
                dep_listbox.selection_set(i)

        if is_new:
            ttk.Label(main, text="Status", font=label_font).grid(row=16, column=0, sticky='w', pady=(0,5))
            status_var = tk.StringVar(value='Pending')
            s_frame = ttk.Frame(main)
            s_frame.grid(row=17, column=0, columnspan=2, sticky='w', pady=(0,10))
            for i, s in enumerate(['Pending', 'In Progress', 'Completed', 'Archived']):
                rb = ttk.Radiobutton(s_frame, text=s, variable=status_var, value=s)
                rb.grid(row=0, column=i, padx=10)

        btn_frame = ttk.Frame(main)
        btn_frame.grid(row=18, column=0, columnspan=2, sticky='ew', pady=(10,0))

        def save():
            title = title_entry.get().strip()
            if not title:
                messagebox.showerror("Error", "Title is required")
                return

            desc = desc_text.get('1.0', 'end').strip()
            priority = Priority.from_string(priority_var.get().lower())
            category = cat_entry.get().strip() or 'General'
            tags = [t.strip() for t in tags_entry.get().split(',') if t.strip()]
            effort_str = effort_entry.get().strip()
            effort = int(effort_str) if effort_str.isdigit() else 0
            due_str = due_entry.get().strip()
            due_date = None
            if due_str:
                try:
                    due_date = datetime.strptime(due_str, '%Y-%m-%d %H:%M')
                except ValueError:
                    messagebox.showerror("Invalid Date", "Use YYYY-MM-DD HH:MM format")
                    return

            selected_indices = dep_listbox.curselection()
            dep_ids = []
            for idx in selected_indices:
                item_text = dep_listbox.get(idx)
                prefix = item_text.split(' - ')[0]
                for full_id in dep_id_to_index:
                    if full_id.startswith(prefix):
                        dep_ids.append(full_id)
                        break

            try:
                if is_new:
                    status_val = TaskStatus.from_string(status_var.get().lower())
                    new_task = Task(
                        title=title,
                        description=desc,
                        priority=priority,
                        status=status_val,
                        category=category,
                        due_date=due_date,
                        tags=tags,
                        effort=effort,
                        dependencies=dep_ids
                    )
                    self.manager.add_task(new_task)
                    messagebox.showinfo("Success", f"Task added! ID: {new_task.task_id}")
                else:
                    success = self.manager.update_task(
                        task.task_id,
                        title=title,
                        description=desc,
                        priority=priority,
                        category=category,
                        due_date=due_date,
                        tags=tags,
                        effort=effort,
                        dependencies=dep_ids
                    )
                    if success:
                        messagebox.showinfo("Success", "Task updated!")
                    else:
                        messagebox.showerror("Error", "Update failed")
                        return
            except Exception as e:
                messagebox.showerror("Error", str(e))
                return
            finally:
                dialog.destroy()
                self.refresh_kanban()

        ttk.Button(btn_frame, text="Save", style='Accent.TButton', command=save).pack(side='left', padx=5)
        ttk.Button(btn_frame, text="Cancel", command=dialog.destroy).pack(side='left', padx=5)

        dialog.bind('<Return>', lambda e: save())

    def delete_task(self, task_id):
        if messagebox.askyesno("Confirm Delete", "Delete this task permanently?"):
            self.manager.delete_task(task_id)
            self.refresh_kanban()

    def move_task(self, task_id, new_status):
        self.manager.update_task(task_id, status=new_status)
        self.refresh_kanban()

    def bulk_delete(self):
        if not hasattr(self, 'selected_task_id') or not self.selected_task_id:
            messagebox.showinfo("Info", "No task selected. Click a card to select it.")
            return
        tid = self.selected_task_id
        if messagebox.askyesno("Confirm Delete", "Delete selected task?"):
            self.manager.delete_task(tid)
            self.selected_task_id = None
            self.refresh_kanban()

    def show_stats(self):
        stats = self.manager.get_statistics()
        win = tk.Toplevel(self.root)
        win.title("Statistics")
        win.geometry("500x450")
        win.configure(bg='#f0f2f5')
        try:
            win.attributes('-alpha', 0.95)
        except:
            pass

        main = ttk.Frame(win)
        main.pack(fill='both', expand=True, padx=20, pady=20)

        ttk.Label(main, text="Task Statistics", font=self.title_font).pack(pady=(0,15))

        labels = [
            ("Total", stats['total']),
            ("Completed", stats['completed']),
            ("In Progress", stats['in_progress']),
            ("Pending", stats['pending']),
            ("Archived", stats['archived']),
            ("Overdue", stats['overdue']),
            ("Completion Rate", f"{stats['completion_rate']:.1f}%")
        ]
        for label, value in labels:
            ttk.Label(main, text=f"{label}: {value}", font=self.card_font).pack(anchor='w', pady=2)

        if stats['categories']:
            ttk.Label(main, text="Categories:", font=self.header_font).pack(anchor='w', pady=(10,0))
            for cat, count in sorted(stats['categories'].items()):
                ttk.Label(main, text=f"  {cat}: {count}", font=self.card_font).pack(anchor='w')

        ttk.Button(main, text="Close", style='Accent.TButton', command=win.destroy).pack(pady=15)

    def check_overdue_notifications(self):
        overdue = self.manager.get_overdue_tasks()
        if overdue and HAS_PLYER:
            notification.notify(
                title="Task Manager",
                message=f"You have {len(overdue)} overdue task(s).",
                timeout=5
            )

    def update_status(self):
        total = len(self.manager.tasks)
        overdue = len(self.manager.get_overdue_tasks())
        completed = sum(1 for t in self.manager.tasks.values() if t.status == TaskStatus.COMPLETED)
        rate = (completed / total * 100) if total > 0 else 0
        text = f"Total: {total}  |  Overdue: {overdue}  |  Completed: {completed}  |  Completion: {rate:.1f}%"
        self.canvas.itemconfig(self.status_text, text=text)

    def on_closing(self):
        self.save_config()
        self.root.destroy()


# ================ CLI FRONTEND ================
class TaskCLI:
    def __init__(self):
        self.manager = TaskManager()
        self.parser = self._create_parser()

    def _create_parser(self):
        parser = argparse.ArgumentParser(
            description='Personal Task Management System',
            formatter_class=argparse.RawDescriptionHelpFormatter,
            epilog='''
Examples:
  task add "Complete project" -d "Finish report" -p high -c Work
  task list --status pending --category Work
  task update 1234 --status completed
  task stats
  task gui
            '''
        )

        subparsers = parser.add_subparsers(dest='command', help='Command to execute')

        add_parser = subparsers.add_parser('add', help='Add a new task')
        add_parser.add_argument('title', help='Task title')
        add_parser.add_argument('-d', '--description', help='Task description', default='')
        add_parser.add_argument('-p', '--priority', choices=['low', 'medium', 'high', 'urgent'],
                                default='medium', help='Task priority')
        add_parser.add_argument('-c', '--category', help='Task category', default='General')
        add_parser.add_argument('--due', help='Due date (YYYY-MM-DD HH:MM)', default=None)
        add_parser.add_argument('-t', '--tags', help='Comma-separated tags', default='')
        add_parser.add_argument('-e', '--effort', type=int, help='Effort in minutes', default=0)

        list_parser = subparsers.add_parser('list', help='List tasks')
        list_parser.add_argument('-s', '--status', choices=['pending', 'in_progress', 'completed', 'archived'],
                                 help='Filter by status')
        list_parser.add_argument('-c', '--category', help='Filter by category')
        list_parser.add_argument('-p', '--priority', choices=['low', 'medium', 'high', 'urgent'],
                                 help='Filter by priority')
        list_parser.add_argument('--search', help='Search in title, description, and tags')
        list_parser.add_argument('--overdue', action='store_true', help='Show only overdue tasks')

        update_parser = subparsers.add_parser('update', help='Update a task')
        update_parser.add_argument('task_id', help='Task ID')
        update_parser.add_argument('--title', help='New title')
        update_parser.add_argument('--description', help='New description')
        update_parser.add_argument('--priority', choices=['low', 'medium', 'high', 'urgent'],
                                   help='New priority')
        update_parser.add_argument('--category', help='New category')
        update_parser.add_argument('--due', help='New due date (YYYY-MM-DD HH:MM)')
        update_parser.add_argument('--status', choices=['pending', 'in_progress', 'completed', 'archived'],
                                   help='New status')
        update_parser.add_argument('--tags', help='New comma-separated tags')
        update_parser.add_argument('--effort', type=int, help='New effort in minutes')

        delete_parser = subparsers.add_parser('delete', help='Delete a task')
        delete_parser.add_argument('task_id', help='Task ID')

        subparsers.add_parser('stats', help='Show task statistics')
        subparsers.add_parser('gui', help='Launch GUI mode')

        clear_parser = subparsers.add_parser('clear', help='Clear all tasks')
        clear_parser.add_argument('--force', action='store_true', help='Skip confirmation')

        return parser

    def _format_task(self, task: Task, index: int = -1) -> str:
        prefix = f"{index + 1}. " if index >= 0 else ""
        status_color = "\033[92m" if task.status == TaskStatus.COMPLETED else (
            "\033[91m" if task.is_overdue() else "")
        reset = "\033[0m"

        lines = [
            f"{prefix}{status_color}{task.title}{reset}",
            f"  ID: {task.task_id}",
            f"  Status: {task.status}",
            f"  Priority: {task.priority}",
            f"  Category: {task.category}",
        ]

        if task.tags:
            lines.append(f"  Tags: {', '.join(task.tags)}")
        if task.effort:
            lines.append(f"  Effort: {task.effort} minutes")

        if task.due_date:
            due_str = task.due_date.strftime('%Y-%m-%d %H:%M')
            if task.is_overdue():
                due_str = f"\033[91m{due_str} (OVERDUE)\033[0m"
            lines.append(f"  Due: {due_str}")

        if task.description:
            lines.append(f"  Description: {task.description}")

        if task.dependencies:
            dep_names = []
            for dep_id in task.dependencies:
                dep = self.manager.get_task(dep_id)
                if dep:
                    dep_names.append(f"{dep.title[:20]}")
            if dep_names:
                lines.append(f"  Dependencies: {', '.join(dep_names)}")

        lines.append(f"  Updated: {task.updated_at.strftime('%Y-%m-%d %H:%M')}")
        return '\n'.join(lines)

    def _print_tasks(self, tasks: List[Task], title: str = "Tasks") -> None:
        if not tasks:
            print(f"\nNo {title.lower()} found.")
            return

        print(f"\n{'='*70}")
        print(f"  {title} ({len(tasks)})")
        print('='*70)

        for i, task in enumerate(tasks):
            print(f"\n{self._format_task(task, i)}")
        print(f"\n{'='*70}")

    def run(self, args=None) -> None:
        args = self.parser.parse_args(args)

        if not args.command:
            self.parser.print_help()
            return

        if args.command == 'gui':
            root = tk.Tk()
            app = KanbanGUI(root)
            root.protocol("WM_DELETE_WINDOW", app.on_closing)
            root.mainloop()
            return

        if args.command == 'add':
            due_date = None
            if args.due:
                try:
                    due_date = datetime.strptime(args.due, '%Y-%m-%d %H:%M')
                except ValueError:
                    print("Error: Invalid due date format. Use YYYY-MM-DD HH:MM")
                    return

            tags = [t.strip() for t in args.tags.split(',') if t.strip()] if args.tags else []

            task = Task(
                title=args.title,
                description=args.description,
                priority=Priority.from_string(args.priority),
                category=args.category,
                due_date=due_date,
                tags=tags,
                effort=args.effort
            )
            task_id = self.manager.add_task(task)
            print(f"✓ Task added successfully! ID: {task_id}")

        elif args.command == 'list':
            status = TaskStatus.from_string(args.status) if args.status else None
            priority = Priority.from_string(args.priority) if args.priority else None

            if args.overdue:
                tasks = self.manager.get_overdue_tasks()
                self._print_tasks(tasks, "Overdue Tasks")
            else:
                tasks = self.manager.list_tasks(
                    status=status,
                    category=args.category,
                    priority=priority,
                    search=args.search
                )
                filter_desc = []
                if status:
                    filter_desc.append(f"status={status}")
                if args.category:
                    filter_desc.append(f"category={args.category}")
                if priority:
                    filter_desc.append(f"priority={priority}")
                if args.search:
                    filter_desc.append(f"search='{args.search}'")
                filter_str = f" ({', '.join(filter_desc)})" if filter_desc else ""
                self._print_tasks(tasks, f"Tasks{filter_str}")

        elif args.command == 'update':
            updates = {}
            if args.title:
                updates['title'] = args.title
            if args.description:
                updates['description'] = args.description
            if args.priority:
                updates['priority'] = Priority.from_string(args.priority)
            if args.category:
                updates['category'] = args.category
            if args.due:
                try:
                    updates['due_date'] = datetime.strptime(args.due, '%Y-%m-%d %H:%M')
                except ValueError:
                    print("Error: Invalid due date format. Use YYYY-MM-DD HH:MM")
                    return
            if args.status:
                updates['status'] = TaskStatus.from_string(args.status)
            if args.tags:
                updates['tags'] = [t.strip() for t in args.tags.split(',') if t.strip()]
            if args.effort is not None:
                updates['effort'] = args.effort

            if not updates:
                print("Error: No updates specified")
                return

            if self.manager.update_task(args.task_id, **updates):
                print(f"✓ Task {args.task_id} updated successfully!")
            else:
                print(f"✗ Task {args.task_id} not found")

        elif args.command == 'delete':
            if self.manager.delete_task(args.task_id):
                print(f"✓ Task {args.task_id} deleted successfully!")
            else:
                print(f"✗ Task {args.task_id} not found")

        elif args.command == 'stats':
            stats = self.manager.get_statistics()
            print("\n" + "="*50)
            print("  TASK STATISTICS")
            print("="*50)
            print(f"  Total tasks:     {stats['total']}")
            print(f"  Completed:       {stats['completed']}")
            print(f"  In Progress:     {stats['in_progress']}")
            print(f"  Pending:         {stats['pending']}")
            print(f"  Archived:        {stats['archived']}")
            print(f"  Overdue:         {stats['overdue']}")
            print(f"  Completion Rate: {stats['completion_rate']:.1f}%")
            print("\n  Categories:")
            for category, count in sorted(stats['categories'].items()):
                bar = '█' * int((count / stats['total']) * 30) if stats['total'] > 0 else ''
                print(f"    {category:15} {count:3} {bar}")
            print("="*50)

        elif args.command == 'clear':
            if not args.force:
                confirm = input(f"⚠️  Delete all {len(self.manager.tasks)} tasks? (y/N): ")
                if confirm.lower() != 'y':
                    print("Operation cancelled.")
                    return

            count = len(self.manager.tasks)
            self.manager.tasks.clear()
            self.manager.save_tasks()
            print(f"✓ All {count} tasks cleared successfully!")


# ================ ENTRY POINT ================
def main():
    if len(sys.argv) == 1:
        try:
            root = tk.Tk()
            app = KanbanGUI(root)
            root.protocol("WM_DELETE_WINDOW", app.on_closing)
            root.mainloop()
        except Exception as e:
            print(f"Error starting GUI: {e}")
            print("Make sure you have tkinter installed.")
        return

    cli = TaskCLI()
    try:
        cli.run()
    except KeyboardInterrupt:
        print("\n\nOperation cancelled by user.")
        sys.exit(1)
    except Exception as e:
        print(f"\n✗ An error occurred: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()