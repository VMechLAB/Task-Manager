#!/usr/bin/env python3
"""Task Manager — a kanban board that does its best to look organised."""

import json
import os
import sys
import hashlib
import shutil
import argparse
import re
from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, List, Optional

import tkinter as tk
from tkinter import ttk, messagebox, filedialog

try:
    from plyer import notification
    HAS_PLYER = True
except ImportError:
    HAS_PLYER = False

try:
    from PIL import Image, ImageTk
    HAS_PIL = True
except ImportError:
    HAS_PIL = False


WEEKDAYS = ['monday', 'tuesday', 'wednesday', 'thursday',
            'friday', 'saturday', 'sunday']


def parse_natural_date(text: str) -> Optional[datetime]:
    # Accepts "tomorrow", "friday 5pm", "in 3 days" and other things humans
    # blurt out. Rejects "whenever", "eventually", and "ask my manager".
    text = (text or '').strip().lower()
    if not text:
        return None

    now = datetime.now()          # approximately now. Give or take.
    default_time = (17, 0)        # 5 PM, because that's when adults give up

    def with_time(base_date, time_part=None):
        h, m = time_part or default_time
        return base_date.replace(hour=h, minute=m, second=0, microsecond=0)

    time_match = re.search(r'(\d{1,2})(?::(\d{2}))?\s*(am|pm)?', text)
    explicit_time = None
    if time_match and (time_match.group(3) or ':' in (time_match.group(0) or '')):
        h = int(time_match.group(1))
        m = int(time_match.group(2) or 0)
        ampm = time_match.group(3)
        if ampm == 'pm' and h != 12:
            h += 12
        if ampm == 'am' and h == 12:
            h = 0
        if 0 <= h <= 23 and 0 <= m <= 59:
            explicit_time = (h, m)

    if 'today' in text:
        return with_time(now, explicit_time)
    if 'tomorrow' in text:
        return with_time(now + timedelta(days=1), explicit_time)
    if 'next week' in text:
        return with_time(now + timedelta(days=7), explicit_time)

    m = re.search(r'in\s+(\d+)\s*(day|week)', text)
    if m:
        n = int(m.group(1))
        delta = timedelta(days=n) if m.group(2) == 'day' else timedelta(weeks=n)
        return with_time(now + delta, explicit_time)

    for i, day_name in enumerate(WEEKDAYS):
        if day_name in text or day_name[:3] in text:
            days_ahead = (i - now.weekday()) % 7 or 7
            return with_time(now + timedelta(days=days_ahead), explicit_time)

    formats = ['%Y-%m-%d %H:%M', '%Y-%m-%d', '%m/%d/%Y %H:%M', '%m/%d/%Y',
               '%m/%d %H:%M', '%m/%d', '%d/%m/%Y', '%b %d %Y', '%b %d']
    cleaned = re.sub(r'\s*(am|pm)\b', '', text).strip()
    for fmt in formats:
        try:
            parsed = datetime.strptime(cleaned, fmt)
            if '%Y' not in fmt:
                parsed = parsed.replace(year=now.year)
            if '%H' not in fmt:
                parsed = with_time(parsed, explicit_time)
            return parsed
        except ValueError:
            continue

    raise ValueError(
        "Try 'today', 'tomorrow', 'friday 5pm', 'in 3 days', or 2026-09-30."
    )


def friendly_due(dt: Optional[datetime]) -> str:
    # Turns cold datetime objects into phrases your brain can be bothered
    # to read. "Tomorrow 17:00" beats "2026-09-23 17:00:00" every time.
    if not dt:
        return ''
    now = datetime.now()
    if dt.date() == now.date():
        return f"Today {dt.strftime('%H:%M')}"
    if dt.date() == (now + timedelta(days=1)).date():
        return f"Tomorrow {dt.strftime('%H:%M')}"
    return dt.strftime('%a %d %b %H:%M')

class Priority(Enum):
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    URGENT = 4

    @classmethod
    def from_string(cls, value):
        # Whatever you typed, it's probably "medium". It's always "medium".
        return {'low': cls.LOW, 'medium': cls.MEDIUM,
                'high': cls.HIGH, 'urgent': cls.URGENT
                }.get((value or '').lower(), cls.MEDIUM)

    def __str__(self):
        return self.name.title()


class TaskStatus(Enum):
    PENDING = 'pending'               # hasn't started, may never start
    IN_PROGRESS = 'in_progress'       # open in a tab somewhere
    COMPLETED = 'completed'           # a rare and beautiful event
    ARCHIVED = 'archived'             # the graveyard, respectfully kept

    @classmethod
    def from_string(cls, value):
        key = (value or '').lower().replace(' ', '_')
        return {'pending': cls.PENDING, 'in_progress': cls.IN_PROGRESS,
                'completed': cls.COMPLETED, 'archived': cls.ARCHIVED
                }.get(key, cls.PENDING)

    def __str__(self):
        return self.value.replace('_', ' ').title()


class Task:
    def __init__(self, title, description='', priority=Priority.MEDIUM,
                 status=TaskStatus.PENDING, category='General', due_date=None,
                 tags=None, effort=0, dependencies=None, task_id=None):
        self.title = title
        self.description = description
        self.priority = priority
        self.status = status
        self.category = category
        self.due_date = due_date
        self.tags = tags or []
        self.effort = effort               # in minutes, usually optimistic
        self.dependencies = dependencies or []   # the other tasks to blame
        self.created_at = datetime.now()
        self.updated_at = datetime.now()
        self.task_id = task_id or self._generate_id()

    def _generate_id(self):
        # An 8-character fingerprint. Unique enough, short enough to read
        # out loud over the phone without embarrassment.
        return hashlib.md5(
            f"{self.title}{self.created_at.isoformat()}".encode()
        ).hexdigest()[:8]

    def to_dict(self):
        # Flattening ourselves into JSON. It's not therapy, but it's close.
        return {
            'task_id': self.task_id, 'title': self.title,
            'description': self.description, 'priority': self.priority.value,
            'status': self.status.value, 'category': self.category,
            'due_date': self.due_date.isoformat() if self.due_date else None,
            'tags': self.tags, 'effort': self.effort,
            'dependencies': self.dependencies,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data):
        # Rebuilding ourselves from JSON. Trust the process.
        try:
            priority = Priority(data.get('priority', 2))
        except ValueError:
            priority = Priority.MEDIUM
        task = cls(
            title=data['title'],
            description=data.get('description', ''),
            priority=priority,
            status=TaskStatus.from_string(data.get('status', 'pending')),
            category=data.get('category', 'General'),
            due_date=datetime.fromisoformat(data['due_date'])
                     if data.get('due_date') else None,
            tags=data.get('tags', []),
            effort=data.get('effort', 0),
            dependencies=data.get('dependencies', []),
            task_id=data.get('task_id'),
        )
        task.created_at = datetime.fromisoformat(data['created_at'])
        task.updated_at = datetime.fromisoformat(data['updated_at'])
        return task

    def update(self, **kwargs):
        for k, v in kwargs.items():
            if hasattr(self, k):
                setattr(self, k, v)
        self.updated_at = datetime.now()

    def is_overdue(self):
        if not self.due_date or self.status == TaskStatus.COMPLETED:
            return False
        return datetime.now() > self.due_date

    def is_blocked(self, manager):
        for dep_id in self.dependencies:
            dep = manager.get_task(dep_id)
            if dep and dep.status != TaskStatus.COMPLETED:
                return True
        return False


class TaskManager:

    def __init__(self, storage_file='tasks.json'):
        self.storage_file = storage_file
        self.backup_file = storage_file + '.backup'
        self.tasks: Dict[str, Task] = {}
        self.load_tasks()

    def add_task(self, task):
        self.tasks[task.task_id] = task
        self.save_tasks()
        return task.task_id

    def get_task(self, task_id):
        return self.tasks.get(task_id)

    def update_task(self, task_id, **kwargs):
        task = self.get_task(task_id)
        if not task:
            return False
        task.update(**kwargs)
        self.save_tasks()
        return True

    def delete_task(self, task_id):
        if task_id in self.tasks:
            for t in self.tasks.values():
                if task_id in t.dependencies:
                    t.dependencies.remove(task_id)
            del self.tasks[task_id]
            self.save_tasks()
            return True
        return False

    def list_tasks(self, status=None, category=None, priority=None, search=None):
        # Filter, filter, filter, sort. The eternal cycle of task life.
        filtered = list(self.tasks.values())
        if status:
            filtered = [t for t in filtered if t.status == status]
        if category:
            filtered = [t for t in filtered
                        if t.category.lower() == category.lower()]
        if priority:
            filtered = [t for t in filtered if t.priority == priority]
        if search:
            s = search.lower()
            filtered = [t for t in filtered
                        if s in t.title.lower()
                        or s in t.description.lower()
                        or any(s in tag.lower() for tag in t.tags)]
        filtered.sort(key=lambda t: (t.due_date or datetime.max,
                                     -t.priority.value))
        return filtered

    def get_overdue_tasks(self):
        return [t for t in self.tasks.values() if t.is_overdue()]

    def get_statistics(self):
        # Numbers that make you feel either productive or judged.
        total = len(self.tasks)
        by_status = {s: 0 for s in TaskStatus}
        for t in self.tasks.values():
            by_status[t.status] += 1
        categories = {}
        for task in self.tasks.values():
            categories[task.category] = categories.get(task.category, 0) + 1
        return {
            'total': total,
            'completed': by_status[TaskStatus.COMPLETED],
            'pending': by_status[TaskStatus.PENDING],
            'in_progress': by_status[TaskStatus.IN_PROGRESS],
            'archived': by_status[TaskStatus.ARCHIVED],
            'overdue': len(self.get_overdue_tasks()),
            'completion_rate': (by_status[TaskStatus.COMPLETED] / total * 100)
                                if total else 0,
            'categories': categories,
        }

    def save_tasks(self):
        if os.path.exists(self.storage_file):
            shutil.copy2(self.storage_file, self.backup_file)
        data = {
            'tasks': [t.to_dict() for t in self.tasks.values()],
            'last_updated': datetime.now().isoformat(),
        }
        try:
            with open(self.storage_file, 'w') as f:
                json.dump(data, f, indent=2)
        except IOError as e:
            print(f"Error saving: {e}", file=sys.stderr)

    def load_tasks(self):
        if not os.path.exists(self.storage_file):
            return
        try:
            with open(self.storage_file, 'r') as f:
                data = json.load(f)
            for td in data.get('tasks', []):
                t = Task.from_dict(td)
                self.tasks[t.task_id] = t
        except (IOError, json.JSONDecodeError, KeyError) as e:
            print(f"Error loading: {e}", file=sys.stderr)
            if os.path.exists(self.backup_file):
                try:
                    with open(self.backup_file) as f:
                        data = json.load(f)
                    for td in data.get('tasks', []):
                        t = Task.from_dict(td)
                        self.tasks[t.task_id] = t
                except Exception:
                    self.tasks = {}


#GUI palette
# Colours chosen with confidence and at least one cup of coffee.
BG_APP = "#fcf6f0"
BG_HEADER = "#010A00"
BG_BOARD = "#f8fff7"
BG_COLUMN = '#ffffff'
BG_INPUT = "#f0ede8"
FG_PRIMARY = "#04300A"
FG_SECONDARY = "#4f7554"
FG_MUTED = "#89b898"
ACCENT = "#3e9b21"
ACCENT_HOVER = "#05790b"
BORDER = "#f0e8e2"

PRIORITY_COLORS = {
    Priority.LOW: "#00ff9d",        # a gentle nudge from the universe
    Priority.MEDIUM: "#ffb028",     # fine, but you know, get on with it
    Priority.HIGH: "#df5e03",       # actively on fire
    Priority.URGENT: "#ff2828",     # why is this not done yet
}

COLUMNS = [
    ('To Do', TaskStatus.PENDING, "#9cacd8"),
    ('In Progress', TaskStatus.IN_PROGRESS, "#a58416"),
    ('Done', TaskStatus.COMPLETED, '#10b981'),
    ('Archived', TaskStatus.ARCHIVED, "#808083"),
]


def _walk(widget):
    yield widget
    for child in widget.winfo_children():
        yield from _walk(child)


class PlaceholderEntry(tk.Entry):

    def __init__(self, master, placeholder='', **kwargs):
        self._fg = kwargs.get('fg', FG_PRIMARY)
        super().__init__(master, **kwargs)
        self._placeholder = placeholder
        self._active = False
        self.bind('<FocusIn>', self._on_focus_in)
        self.bind('<FocusOut>', self._on_focus_out)
        self._show_placeholder()

    def _show_placeholder(self):
        if not super().get():
            self._active = True
            super().insert(0, self._placeholder)
            self.configure(fg=FG_MUTED)

    def _on_focus_in(self, _e=None):
        # The user noticed us. Time to drop the act.
        if self._active:
            self._active = False
            super().delete(0, 'end')
            self.configure(fg=self._fg)

    def _on_focus_out(self, _e=None):
        if not super().get():
            self._show_placeholder()

    def clear(self):
        self._active = False
        super().delete(0, 'end')
        if self.focus_get() is not self:
            self._show_placeholder()

    def get(self):
        if self._active:
            return ''
        return super().get()


class Toast:

    def __init__(self, root, message, kind='info', duration=2000):
        colors = {'info': '#334155', 'success': '#059669', 'error': '#dc2626'}
        bg = colors.get(kind, colors['info'])
        self.frame = tk.Frame(root, bg=bg, padx=18, pady=10)
        tk.Label(self.frame, text=message, bg=bg, fg='white',
                 font=('Segoe UI', 10)).pack()
        self.frame.place(relx=1.0, rely=1.0, x=-24, y=-24, anchor='se')
        self.frame.lift()
        root.after(duration, self._destroy)

    def _destroy(self):
        try:
            self.frame.destroy()
        except Exception:
            pass


class TaskCard(tk.Frame):

    def __init__(self, parent, app, task):
        super().__init__(parent, bg='white', bd=0,
                         highlightthickness=1, highlightbackground=BORDER,
                         cursor='hand2')
        self.app = app
        self.task = task
        self._build()
        self._bind_all()
        self._bind_drag()

    def _build(self):
        # Assemble the card like flat-pack furniture. Everything clicks.
        t = self.task
        stripe_color = PRIORITY_COLORS.get(t.priority, '#94a3b8')

        tk.Frame(self, bg=stripe_color, width=4).pack(side='left', fill='y')

        body = tk.Frame(self, bg='white')
        body.pack(side='left', fill='both', expand=True, padx=12, pady=10)

        title = t.title if len(t.title) <= 60 else t.title[:59] + '...'
        tk.Label(body, text=title, bg='white', fg=FG_PRIMARY,
                 font=self.app.font_card_title, anchor='w', justify='left',
                 wraplength=230).pack(fill='x')

        meta_bits = []
        if t.category and t.category != 'General':
            meta_bits.append(t.category)
        if t.tags:
            meta_bits.append('  '.join(t.tags))
        if meta_bits:
            tk.Label(body, text='  |  '.join(meta_bits), bg='white',
                     fg=FG_SECONDARY, font=self.app.font_small,
                     anchor='w', justify='left',
                     wraplength=230).pack(fill='x', pady=(4, 0))

        footer = tk.Frame(body, bg='white')
        footer.pack(fill='x', pady=(8, 0))

        tk.Label(footer, text=str(t.priority), bg=stripe_color, fg='white',
                 font=self.app.font_tiny, padx=7, pady=1).pack(side='left')

        if t.effort:
            tk.Label(footer, text=self.app.format_effort(t.effort),
                     bg='white', fg=FG_MUTED,
                     font=self.app.font_tiny).pack(side='left', padx=(8, 0))

        if t.due_date:
            overdue = t.is_overdue()
            color = '#dc2626' if overdue else FG_SECONDARY
            text = 'OVERDUE  ' + friendly_due(t.due_date) if overdue \
                   else friendly_due(t.due_date)
            tk.Label(footer, text=text, bg='white', fg=color,
                     font=self.app.font_tiny).pack(side='right')

        if t.is_blocked(self.app.manager):
            tk.Label(body, text='Blocked by dependency', bg='#fef3c7',
                     fg='#92400e', font=self.app.font_tiny, padx=6,
                     pady=1).pack(anchor='w', pady=(6, 0))

    def _bind_all(self):
        for w in _walk(self):
            w.bind('<Double-Button-1>',
                   lambda e: self.app.edit_task_dialog(self.task.task_id))
            w.bind('<Button-3>',
                   lambda e: self.app.show_card_menu(e, self.task.task_id))
            w.bind('<Enter>', lambda e: self.configure(
                highlightbackground=ACCENT), add='+')
            w.bind('<Leave>', lambda e: self.configure(
                highlightbackground=BORDER), add='+')

    def _bind_drag(self):

        def start(_e):
            self.app.drag_task_id = self.task.task_id
            self.configure(highlightbackground=ACCENT_HOVER,
                           highlightthickness=2)

        def stop(e):
            self.configure(highlightbackground=BORDER, highlightthickness=1)
            target = self.app.find_column_at(e.x_root, e.y_root)
            if target and self.app.drag_task_id:
                self.app.move_task(self.app.drag_task_id, target)
            self.app.drag_task_id = None

        for w in _walk(self):
            w.bind('<ButtonPress-1>', start, add='+')
            w.bind('<ButtonRelease-1>', stop, add='+')


class Column(tk.Frame):
    """A kanban column whose background shows the board's background image
    through a soft frosted-glass veil. Task cards float on top."""

    HEADER_H = 56

    def __init__(self, parent, app, title, status, accent):
        super().__init__(parent, bg=BG_BOARD, bd=0, highlightthickness=0)
        self.app = app
        self.status = status
        self.title = title
        self.accent = accent

        self.canvas = tk.Canvas(self, bg=BG_BOARD, highlightthickness=0, bd=0,
                                yscrollincrement=20)
        self.canvas.pack(side='left', fill='both', expand=True)

        self.scrollbar = ttk.Scrollbar(self, orient='vertical',
                                       command=self.canvas.yview)
        self.scrollbar.pack(side='right', fill='y')
        self.canvas.configure(yscrollcommand=self.scrollbar.set)

        # State we have to keep because tkinter doesn't do it for us.
        self._bg_id = None
        self._bg_photo = None
        self._tint_id = None
        self._card_windows = {}
        self._header_ids = {}
        self._empty_id = None
        self._content_h = 100

        self._draw_header()

        self.canvas.bind('<Configure>', self._on_resize)
        self.canvas.bind('<Enter>',
                         lambda e: self.canvas.bind_all('<MouseWheel>', self._wheel))
        self.canvas.bind('<Leave>',
                         lambda e: self.canvas.unbind_all('<MouseWheel>'))

    def _draw_header(self):
        # Draw the header by hand on the canvas so it can float above the
        # background image without a chunk of white ruining the mood.
        c = self.canvas
        self._header_ids['accent'] = c.create_rectangle(
            0, 0, 0, 0, fill=self.accent, outline='')
        self._header_ids['title'] = c.create_text(
            0, 0, anchor='w', text=self.title,
            fill=FG_PRIMARY, font=self.app.font_header)
        self._header_ids['count'] = c.create_text(
            0, 0, anchor='e', text='0',
            fill=FG_SECONDARY, font=self.app.font_small)
        self._header_ids['plus'] = c.create_text(
            0, 0, anchor='e', text='+',
            fill=FG_MUTED, font=(self.app.fam, 18, 'normal'))
        c.tag_bind(self._header_ids['plus'], '<Button-1>',
                   lambda e: self.app.add_task_dialog(default_status=self.status))
        c.tag_bind(self._header_ids['plus'], '<Enter>',
                   lambda e: c.itemconfig(self._header_ids['plus'], fill=ACCENT))
        c.tag_bind(self._header_ids['plus'], '<Leave>',
                   lambda e: c.itemconfig(self._header_ids['plus'], fill=FG_MUTED))

    def _wheel(self, e):
        self.canvas.yview_scroll(int(-1 * (e.delta / 120)), 'units')
        self._pin()

    def _pin(self):
        """Pin the bg crop, tint and header to the viewport so they stay
        fixed while the cards scroll past like scenery out a train window."""
        c = self.canvas
        top = c.canvasy(0)
        w = c.winfo_width()
        h = c.winfo_height()

        if self._bg_id:
            c.coords(self._bg_id, 0, top)
        if self._tint_id:
            c.coords(self._tint_id, 0, top, w, top + h)

        ids = self._header_ids
        if 'accent' in ids:
            c.coords(ids['accent'], 14, top + 20, 18, top + 36)
        if 'title' in ids:
            c.coords(ids['title'], 28, top + 28)
        if 'count' in ids:
            c.coords(ids['count'], w - 44, top + 28)
        if 'plus' in ids:
            c.coords(ids['plus'], w - 20, top + 27)

    def _on_resize(self, e):
        for wid in self._card_windows.values():
            self.canvas.itemconfig(wid, width=max(e.width - 16, 60))
        self.canvas.configure(scrollregion=(0, 0, e.width, self._content_h))
        self._pin()

    def set_bg_crop(self, pil_img):
        """Hand this column the slice of the background image that lines up
        with where it sits on the board, then drop a translucent white veil
        over it. Cards sit on top. Everyone is happy."""
        w = max(self.canvas.winfo_width(), 40)
        h = max(self.canvas.winfo_height(), 40)
        try:
            img = pil_img.resize((w, h), Image.LANCZOS)
        except Exception:
            return
        self._bg_photo = ImageTk.PhotoImage(img)

        if self._bg_id:
            self.canvas.itemconfig(self._bg_id, image=self._bg_photo)
        else:
            self._bg_id = self.canvas.create_image(
                0, 0, anchor='nw', image=self._bg_photo)

        if not self._tint_id:
            # 50% white stipple = frosted glass. The image shows through
            # the remaining 50%. Bump to gray25 for a bolder image, or
            # gray75 for a stronger veil when the text fights back.
            self._tint_id = self.canvas.create_rectangle(
                0, 0, w, h, fill='white', outline='', stipple='gray50')

        self._fix_order()
        self._pin()

    def clear_bg(self):
        if self._bg_id:
            self.canvas.delete(self._bg_id)
            self._bg_id = None
        if self._tint_id:
            self.canvas.delete(self._tint_id)
            self._tint_id = None

    def _fix_order(self):
        """Background at the back, veil in front of it, header on top of
        everything. A tiny z-index caste system."""
        if self._bg_id:
            self.canvas.tag_lower(self._bg_id)
        if self._tint_id and self._bg_id:
            self.canvas.tag_raise(self._tint_id, self._bg_id)
        for iid in self._header_ids.values():
            if self._tint_id:
                self.canvas.tag_raise(iid, self._tint_id)
            else:
                self.canvas.tag_raise(iid)

    def render(self, tasks):
        # Wipe the slate, then draw every card for this status. Yes, this
        # is what they mean by "re-render". Very glamorous.
        for wid in self._card_windows.values():
            self.canvas.delete(wid)
        self._card_windows.clear()
        if self._empty_id:
            self.canvas.delete(self._empty_id)
            self._empty_id = None

        self.canvas.itemconfig(self._header_ids['count'], text=str(len(tasks)))

        w = self.canvas.winfo_width() or 240
        start_y = self.HEADER_H

        if not tasks:
            self._empty_id = self.canvas.create_text(
                w // 2, start_y + 30, text='No tasks',
                fill=FG_MUTED, font=self.app.font_small)
            self._content_h = start_y + 60
            self.canvas.configure(scrollregion=(0, 0, w, self._content_h))
            self._fix_order()
            self._pin()
            return

        y = start_y
        for task in tasks:
            card = TaskCard(self.canvas, self.app, task)
            wid = self.canvas.create_window(
                8, y, anchor='nw', window=card, width=max(w - 16, 80))
            self._card_windows[task.task_id] = wid
            card.update_idletasks()
            # Stack the next card just below this one, with a polite gap.
            y += max(card.winfo_reqheight(), 50) + 8

        self._content_h = y + 8
        self.canvas.configure(scrollregion=(0, 0, w, self._content_h))
        self._fix_order()
        self._pin()


class KanbanGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Tasks")
        self.root.geometry("1280x780")
        self.root.minsize(920, 560)
        self.root.configure(bg=BG_APP)

        self.manager = TaskManager()
        self.config = {}
        self._load_config()
        fam = "Segoe UI" if sys.platform.startswith('win') else "Helvetica"
        self.fam = fam
        self.font_app_title = (fam, 15, 'bold')
        self.font_stats = (fam, 10)
        self.font_header = (fam, 11, 'bold')
        self.font_card_title = (fam, 10, 'bold')
        self.font_normal = (fam, 10)
        self.font_small = (fam, 9)
        self.font_tiny = (fam, 8, 'bold')

        self.drag_task_id = None
        self.filter_priority = tk.StringVar(value='All')
        self._bg_pil = None
        self._bg_resize_job = None

        self._setup_style()
        self._build_layout()
        self.refresh()

        self.root.bind('<Control-n>', lambda e: self.add_task_dialog())
        self.root.bind('<Control-f>',
                       lambda e: (self.search_entry.focus_set(), 'break'))
        self.root.bind('<Configure>', self._on_root_configure)

        # Wait a beat for the layout to settle, then paint the background.
        # Yes, 120ms. No, we will not be measuring it.
        self.root.after(120, self.apply_background)

    #config
    def _load_config(self):
        # Read our tiny config file. If it's broken, pretend it isn't.
        self.config_file = "config.json"
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r') as f:
                    self.config = json.load(f)
            except Exception:
                pass

    def _save_config(self):
        # Write the config. If this fails, it's fine. Nobody dies.
        try:
            with open(self.config_file, 'w') as f:
                json.dump(self.config, f, indent=2)
        except Exception:
            pass

    #styling
    def _setup_style(self):
        # Tame ttk and its many, many opinions. The 'clam' theme is the
        # only one that does what we ask without sulking.
        style = ttk.Style()
        try:
            style.theme_use('clam')
        except Exception:
            pass

        style.configure('TFrame', background=BG_APP)
        style.configure('TLabel', background=BG_APP, foreground=FG_PRIMARY,
                        font=self.font_normal)

        style.configure('Accent.TButton', background=ACCENT, foreground='white',
                        font=(self.fam, 10, 'bold'), padding=(14, 8),
                        borderwidth=0, relief='flat')
        style.map('Accent.TButton',
                  background=[('active', ACCENT_HOVER), ('pressed', ACCENT_HOVER)])

        style.configure('Ghost.TButton', background='#eef2ff',
                        foreground=ACCENT_HOVER, font=self.font_normal,
                        padding=(12, 7), borderwidth=0, relief='flat')
        style.map('Ghost.TButton', background=[('active', '#e0e7ff')])

        style.configure('Danger.TButton', background='#ef4444',
                        foreground='white', font=self.font_normal,
                        padding=(12, 7), borderwidth=0, relief='flat')
        style.map('Danger.TButton', background=[('active', '#dc2626')])

        style.configure('Flat.TCombobox', fieldbackground='white',
                        background='white', bordercolor=BORDER,
                        borderwidth=1, padding=6, relief='flat', arrowsize=14)
        style.map('Flat.TCombobox',
                  fieldbackground=[('readonly', 'white')],
                  bordercolor=[('focus', ACCENT)])

        style.configure('Thin.Vertical.TScrollbar', background='#cbd5e1',
                        troughcolor=BG_BOARD, bordercolor=BG_BOARD,
                        arrowcolor=FG_MUTED, borderwidth=0, width=8)

    #layout
    def _build_layout(self):
        HEADER_H = 76
        header = tk.Frame(self.root, bg=BG_HEADER, height=HEADER_H)
        header.pack(fill='x')
        header.pack_propagate(False)   # we mean it about the height

        tk.Label(header, text="Tasks", bg=BG_HEADER, fg='white',
                 font=self.font_app_title).pack(side='left',
                                                padx=28, pady=(2, 0))

        self.stats_lbl = tk.Label(header, text="", bg=BG_HEADER,
                                  fg='#cbd5e1', font=self.font_stats)
        self.stats_lbl.pack(side='left', padx=(20, 0), pady=(2, 0))

        ttk.Button(header, text="+ New Task", style='Accent.TButton',
                   command=self.add_task_dialog).pack(side='right',
                                                      padx=28, pady=18)
        ttk.Button(header, text="Stats", style='Ghost.TButton',
                   command=self.show_stats).pack(side='right', padx=(0, 8),
                                                 pady=18)
        ttk.Button(header, text="Background", style='Ghost.TButton',
                   command=self.choose_background).pack(side='right',
                                                       padx=(0, 8), pady=18)

        #toolbar
        toolbar = tk.Frame(self.root, bg=BG_APP)
        toolbar.pack(fill='x', padx=20, pady=(16, 8))

        search_wrap = tk.Frame(toolbar, bg='white', highlightthickness=1,
                               highlightbackground=BORDER)
        search_wrap.pack(side='left')
        self.search_entry = PlaceholderEntry(
            search_wrap, placeholder='Search tasks...',
            bd=0, bg='white', fg=FG_PRIMARY, font=self.font_normal,
            width=24, insertbackground=FG_PRIMARY)
        self.search_entry.pack(side='left', ipady=8, padx=12)
        self.search_entry.bind('<KeyRelease>', lambda e: self.refresh())

        filter_wrap = tk.Frame(toolbar, bg=BG_APP)
        filter_wrap.pack(side='left', padx=(14, 0))
        tk.Label(filter_wrap, text="Priority:", bg=BG_APP, fg=FG_SECONDARY,
                 font=self.font_small).pack(side='left', padx=(0, 6))
        prio_menu = ttk.Combobox(filter_wrap, textvariable=self.filter_priority,
                                 state='readonly', width=10,
                                 values=['All', 'Low', 'Medium', 'High', 'Urgent'],
                                 font=self.font_normal, style='Flat.TCombobox')
        prio_menu.pack(side='left')
        prio_menu.bind('<<ComboboxSelected>>', lambda e: self.refresh())

        add_wrap = tk.Frame(toolbar, bg='white', highlightthickness=1,
                            highlightbackground=BORDER)
        add_wrap.pack(side='right', fill='x', expand=True, padx=(24, 0))

        self.quick_entry = PlaceholderEntry(
            add_wrap, placeholder='Quick add a task and press Enter...',
            bd=0, bg='white', fg=FG_PRIMARY, font=self.font_normal,
            insertbackground=FG_PRIMARY)
        self.quick_entry.pack(side='left', fill='x', expand=True,
                              ipady=8, padx=12)
        self.quick_entry.bind('<Return>', lambda e: self.quick_add())

        ttk.Button(add_wrap, text="Add", style='Accent.TButton',
                   command=self.quick_add).pack(side='right', padx=4, pady=3)

        #board
        self.board = tk.Frame(self.root, bg=BG_BOARD)
        self.board.pack(fill='both', expand=True, padx=20, pady=(8, 16))
        self.board.columnconfigure(tuple(range(len(COLUMNS))),
                                   weight=1, uniform='col')
        self.board.rowconfigure(0, weight=1)

        # The background image label, quietly hugging the bottom of the
        # stacking order so the columns and cards can float above it.
        self.board_bg_label = tk.Label(self.board, bd=0, bg=BG_BOARD)
        self.board_bg_label.place(x=0, y=0, relwidth=1, relheight=1)
        self.board_bg_label.lower()

        self.column_frames = {}
        for i, (name, status, accent) in enumerate(COLUMNS):
            col = Column(self.board, self, name, status, accent)
            pad_l = 0 if i == 0 else 6
            pad_r = 0 if i == len(COLUMNS) - 1 else 6
            col.grid(row=0, column=i, sticky='nsew', padx=(pad_l, pad_r))
            self.column_frames[status] = col

        #status bar
        self.status_bar = tk.Label(self.root, text="", bg=BG_APP,
                                   fg=FG_MUTED, font=self.font_small,
                                   anchor='w')
        self.status_bar.pack(fill='x', padx=24, pady=(0, 8))

    #background
    def choose_background(self):
        # Let the user pick a picture. We file it next to the script so it
        # survives a reboot and a mild amount of neglect.
        if not HAS_PIL:
            messagebox.showinfo(
                "Background image",
                "Install Pillow to use a background image:\n\npip install pillow")
            return
        path = filedialog.askopenfilename(
            title="Choose a background image",
            filetypes=[("Images", "*.png *.jpg *.jpeg *.gif *.bmp"),
                       ("All files", "*.*")])
        if not path:
            return
        try:
            dest = os.path.join(os.getcwd(), "background.png")
            img = Image.open(path).convert('RGB')
            img.save(dest, 'PNG')
            self.config['background'] = dest
            self._save_config()
            self.apply_background()
            Toast(self.root, "Background updated", kind='success')
        except Exception as e:
            messagebox.showerror("Error", f"Couldn't set background: {e}")

    def apply_background(self):
        """Stretch the image to board size, then hand each column its own
        crop so the whole thing reads as one continuous background. This
        is the trick that makes the columns look transparent."""
        path = self.config.get('background')

        if not (HAS_PIL and path and os.path.exists(path)):
            # No picture, no problem. Just wipe any stale backdrop.
            self._bg_pil = None
            self.board_bg_label.configure(image='')
            self.board_bg_label.image = None
            for col in self.column_frames.values():
                col.clear_bg()
            return

        self.root.update_idletasks()
        bw = self.board.winfo_width()
        bh = self.board.winfo_height()
        if bw < 50 or bh < 50:
            # We were called before the layout existed. Try again shortly.
            self.root.after(120, self.apply_background)
            return

        try:
            img = Image.open(path).convert('RGB').resize(
                (bw, bh), Image.LANCZOS)
        except Exception as e:
            print(f"Background load failed: {e}")
            return

        self._bg_pil = img

        # Board-level backdrop. This fills the gaps between columns.
        self._board_bg_photo = ImageTk.PhotoImage(img)
        self.board_bg_label.configure(image=self._board_bg_photo)
        self.board_bg_label.image = self._board_bg_photo
        self.board_bg_label.lower()

        # Per-column crops, so each column sees its own slice of the image.
        for status, col in self.column_frames.items():
            try:
                cx = col.winfo_x()
                cy = col.winfo_y()
                canvas = col.canvas
                ccx = cx + canvas.winfo_x()
                ccy = cy + canvas.winfo_y()
                ccw = max(canvas.winfo_width(), 40)
                cch = max(canvas.winfo_height(), 40)
            except Exception:
                continue
            # Clamp the crop rect so we never ask PIL for negative pixels.
            x0 = max(0, min(ccx, bw - 1))
            y0 = max(0, min(ccy, bh - 1))
            x1 = max(x0 + 1, min(ccx + ccw, bw))
            y1 = max(y0 + 1, min(ccy + cch, bh))
            try:
                crop = img.crop((x0, y0, x1, y1))
                col.set_bg_crop(crop)
            except Exception:
                continue

    def _on_root_configure(self, event):
        # Resize events fire constantly. Debounce so we don't repaint the
        # background 60 times a second like some kind of excited puppy.
        if event.widget is not self.root:
            return
        if self._bg_resize_job:
            self.root.after_cancel(self._bg_resize_job)
        self._bg_resize_job = self.root.after(220, self.apply_background)

    #helpers 
    def find_column_at(self, x_root, y_root):
        # Which column is under this pixel? Used to decide where a dragged
        # card should land. The magic trick behind the drag-drop feel.
        for status, col in self.column_frames.items():
            wx, wy = col.winfo_rootx(), col.winfo_rooty()
            ww, wh = col.winfo_width(), col.winfo_height()
            if wx <= x_root <= wx + ww and wy <= y_root <= wy + wh:
                return status
        return None

    def format_effort(self, minutes):
        # 90 minutes is "1h 30m", not "90m". Small mercies.
        if minutes < 60:
            return f"{minutes}m"
        h, m = divmod(minutes, 60)
        return f"{h}h {m}m" if m else f"{h}h"

    #refresh
    def refresh(self):
        # Rebuild the board. The single source of truth for "what's on
        # screen right now". Called often. Very often. Sorry, CPU.
        search = self.search_entry.get().strip() or None
        pf = self.filter_priority.get()
        priority = None if pf == 'All' else Priority.from_string(pf)

        for status, col in self.column_frames.items():
            tasks = self.manager.list_tasks(
                status=status, priority=priority, search=search)
            col.render(tasks)

        stats = self.manager.get_statistics()
        self.stats_lbl.configure(
            text=f"{stats['total']} tasks   |   "
                 f"{stats['completion_rate']:.0f}% done   |   "
                 f"{stats['overdue']} overdue")
        self.status_bar.configure(
            text="Double-click a card to edit  |  drag between columns to "
                 "change status  |  right-click for more  |  "
                 "Ctrl+N new  |  Ctrl+F search")

        # The columns may have changed size after render, so re-slice the
        # background. Slightly wasteful, entirely reliable.
        self.root.after(20, self.apply_background)

    #actions
    def quick_add(self):
        # Type, Enter, done. The fast lane for "I'll deal with the details
        # later". Which is every task, ever.
        title = self.quick_entry.get().strip()
        if not title:
            return
        self.manager.add_task(Task(title=title))
        self.quick_entry.clear()
        self.quick_entry.focus_set()
        self.refresh()
        Toast(self.root, f"Added: {title}", kind='success')

    def move_task(self, task_id, new_status):
        # Fired when a card gets dragged into another column.
        task = self.manager.get_task(task_id)
        if not task or task.status == new_status:
            return
        self.manager.update_task(task_id, status=new_status)
        self.refresh()
        Toast(self.root, f"Moved to {new_status}", kind='success')

    def show_card_menu(self, event, task_id):
        # Right-click menu. The "I have options" moment of every card.
        task = self.manager.get_task(task_id)
        if not task:
            return
        menu = tk.Menu(self.root, tearoff=0)
        menu.add_command(label="Edit...",
                         command=lambda: self.edit_task_dialog(task_id))
        menu.add_separator()
        for name, status, _ in COLUMNS:
            if status != task.status:
                menu.add_command(
                    label=f"Move to {name}",
                    command=lambda s=status: self.move_task(task_id, s))
        menu.add_separator()
        menu.add_command(label="Delete",
                         command=lambda: self.delete_task(task_id))
        menu.tk_popup(event.x_root, event.y_root)

    def delete_task(self, task_id):
        # Confirm first. We're not monsters.
        task = self.manager.get_task(task_id)
        if not task:
            return
        if messagebox.askyesno("Delete", f'Delete "{task.title}"?'):
            self.manager.delete_task(task_id)
            self.refresh()
            Toast(self.root, "Task deleted", kind='info')

    def add_task_dialog(self, default_status=None):
        self.edit_task_dialog(None, is_new=True, default_status=default_status)

    #editor
    def edit_task_dialog(self, task_id=None, is_new=False, default_status=None):
        # One dialog to rule them all: creates new tasks, edits old ones,
        # and looks reasonable doing it. Mostly.
        if is_new:
            task = Task(title="", status=default_status or TaskStatus.PENDING)
        else:
            task = self.manager.get_task(task_id)
            if not task:
                return

        dlg = tk.Toplevel(self.root)
        dlg.title("New Task" if is_new else "Edit Task")
        dlg.configure(bg='white')
        dlg.transient(self.root)
        dlg.grab_set()
        dlg.resizable(False, False)

        pad = tk.Frame(dlg, bg='white', padx=28, pady=24)
        pad.pack(fill='both', expand=True)

        # Small helpers so we don't repeat the same grid config 12 times.
        def section(text, row, pady=(14, 4)):
            tk.Label(pad, text=text, bg='white', fg=FG_SECONDARY,
                     font=self.font_small, anchor='w').grid(
                row=row, column=0, columnspan=2, sticky='ew', pady=pady)

        def make_entry(row, col=0, colspan=1, padx=1):
            e = tk.Entry(pad, font=self.font_normal, bd=0, bg=BG_INPUT,
                         fg=FG_PRIMARY, insertbackground=FG_PRIMARY,
                         highlightthickness=1, highlightbackground=BORDER,
                         highlightcolor=ACCENT)
            e.grid(row=row, column=col, columnspan=colspan, sticky='ew',
                   ipady=6, padx=padx)
            return e

        section("Title", 0, pady=(0, 4))
        title_entry = tk.Entry(pad, font=(self.fam, 12), bd=0, bg=BG_INPUT,
                               fg=FG_PRIMARY, insertbackground=FG_PRIMARY,
                               highlightthickness=1,
                               highlightbackground=BORDER,
                               highlightcolor=ACCENT)
        title_entry.grid(row=1, column=0, columnspan=2, sticky='ew',
                         ipady=8, padx=1)
        if not is_new:
            title_entry.insert(0, task.title)
        title_entry.focus_set()    # cursor starts here, as nature intended

        section("Description", 2)
        desc_text = tk.Text(pad, height=3, font=self.font_normal, bd=0,
                            bg=BG_INPUT, fg=FG_PRIMARY,
                            insertbackground=FG_PRIMARY,
                            highlightthickness=1,
                            highlightbackground=BORDER,
                            highlightcolor=ACCENT, padx=8, pady=6,
                            wrap='word')
        desc_text.grid(row=3, column=0, columnspan=2, sticky='ew', padx=1)
        if not is_new:
            desc_text.insert('1.0', task.description)

        section("Priority", 4)
        prio_frame = tk.Frame(pad, bg='white')
        prio_frame.grid(row=5, column=0, columnspan=2, sticky='w')
        priority_var = tk.StringVar(value=task.priority.name.title())
        for p in ['Low', 'Medium', 'High', 'Urgent']:
            ttk.Radiobutton(prio_frame, text=p, variable=priority_var,
                            value=p).pack(side='left', padx=(0, 12))

        tk.Label(pad, text="Category", bg='white', fg=FG_SECONDARY,
                 font=self.font_small, anchor='w').grid(
            row=6, column=0, sticky='ew', pady=(14, 4))
        tk.Label(pad, text="Effort (min)", bg='white', fg=FG_SECONDARY,
                 font=self.font_small, anchor='w').grid(
            row=6, column=1, sticky='ew', padx=(13, 0), pady=(14, 4))

        cat_entry = make_entry(7, col=0, padx=(1, 6))
        cat_entry.insert(0, task.category if not is_new else 'General')
        effort_entry = make_entry(7, col=1, padx=(7, 1))
        if not is_new and task.effort:
            effort_entry.insert(0, str(task.effort))

        section("Tags (comma-separated)", 8)
        tags_entry = make_entry(9, colspan=2)
        if not is_new:
            tags_entry.insert(0, ', '.join(task.tags))

        section("Due date", 10)
        due_entry = make_entry(11, colspan=2)
        if not is_new and task.due_date:
            due_entry.insert(0, task.due_date.strftime('%Y-%m-%d %H:%M'))

        tk.Label(pad, text='e.g.  tomorrow   friday 5pm   in 3 days   '
                            '2026-09-30',
                 bg='white', fg=FG_MUTED, font=self.font_small,
                 anchor='w').grid(row=12, column=0, columnspan=2,
                                  sticky='w', pady=(4, 0))

        quick_row = tk.Frame(pad, bg='white')
        quick_row.grid(row=13, column=0, columnspan=2, sticky='w',
                       pady=(8, 0))

        def set_due(text):
            # Wipe and replace. The one-liner of due-date entry.
            due_entry.delete(0, 'end')
            due_entry.insert(0, text)

        # "I can't be bothered to type a date" starter pack.
        for txt, val in [("Today", "today"), ("Tomorrow", "tomorrow"),
                         ("+1 week", "in 1 week"), ("Clear", "")]:
            ttk.Button(quick_row, text=txt, style='Ghost.TButton',
                       command=lambda v=val: set_due(v)).pack(
                side='left', padx=(0, 6))

        btn_row = tk.Frame(pad, bg='white')
        btn_row.grid(row=14, column=0, columnspan=2, sticky='ew',
                     pady=(22, 0))

        def save():
            # Validate, collect, commit. The three-step dance of every form
            # ever written since the dawn of buttons.
            title = title_entry.get().strip()
            if not title:
                messagebox.showerror("Missing title", "Please enter a title.")
                return
            try:
                due = parse_natural_date(due_entry.get())
            except ValueError as e:
                messagebox.showerror("Date not understood", str(e))
                return

            desc = desc_text.get('1.0', 'end').strip()
            priority = Priority.from_string(priority_var.get().lower())
            category = cat_entry.get().strip() or 'General'
            tags = [t.strip() for t in tags_entry.get().split(',') if t.strip()]
            es = effort_entry.get().strip()
            effort = int(es) if es.isdigit() else 0

            if is_new:
                self.manager.add_task(Task(
                    title=title, description=desc, priority=priority,
                    status=default_status or TaskStatus.PENDING,
                    category=category, due_date=due, tags=tags, effort=effort))
                msg = "Task created"
            else:
                self.manager.update_task(
                    task.task_id, title=title, description=desc,
                    priority=priority, category=category, due_date=due,
                    tags=tags, effort=effort)
                msg = "Task updated"

            dlg.destroy()
            self.refresh()
            Toast(self.root, msg, kind='success')

        ttk.Button(btn_row, text="Save", style='Accent.TButton',
                   command=save).pack(side='right', padx=(8, 0))
        ttk.Button(btn_row, text="Cancel", style='Ghost.TButton',
                   command=dlg.destroy).pack(side='right')

        if not is_new:
            def del_and_close():
                dlg.destroy()
                self.delete_task(task.task_id)
            ttk.Button(btn_row, text="Delete", style='Danger.TButton',
                       command=del_and_close).pack(side='left')

        # Enter saves, unless the cursor is in the description (where Enter
        # obviously means "new line"). Escape bails out.
        dlg.bind('<Return>',
                 lambda e: None if isinstance(e.widget, tk.Text) else save())
        dlg.bind('<Escape>', lambda e: dlg.destroy())

    #stats
    def show_stats(self):
        # Numbers on a page. Proof that you've been doing *something*.
        stats = self.manager.get_statistics()
        win = tk.Toplevel(self.root)
        win.title("Statistics")
        win.configure(bg='white')
        win.transient(self.root)
        win.resizable(False, False)

        pad = tk.Frame(win, bg='white', padx=28, pady=24)
        pad.pack(fill='both', expand=True)

        tk.Label(pad, text="Statistics", bg='white', fg=FG_PRIMARY,
                 font=(self.fam, 16, 'bold')).pack(anchor='w', pady=(0, 16))

        for label, value in [("Total", stats['total']),
                             ("Pending", stats['pending']),
                             ("In Progress", stats['in_progress']),
                             ("Completed", stats['completed']),
                             ("Archived", stats['archived']),
                             ("Overdue", stats['overdue'])]:
            row = tk.Frame(pad, bg='white')
            row.pack(fill='x', pady=3)
            tk.Label(row, text=label, bg='white', fg=FG_SECONDARY,
                     font=self.font_normal).pack(side='left')
            tk.Label(row, text=str(value), bg='white', fg=FG_PRIMARY,
                     font=(self.fam, 10, 'bold')).pack(side='right')

        tk.Frame(pad, bg=BORDER, height=1).pack(fill='x', pady=16)
        tk.Label(pad, text=f"{stats['completion_rate']:.0f}% complete",
                 bg='white', fg=ACCENT,
                 font=(self.fam, 14, 'bold')).pack(anchor='w')

        if stats['categories']:
            tk.Label(pad, text="By category", bg='white', fg=FG_SECONDARY,
                     font=self.font_small).pack(anchor='w', pady=(16, 6))
            for cat, count in sorted(stats['categories'].items(),
                                     key=lambda x: -x[1]):
                row = tk.Frame(pad, bg='white')
                row.pack(fill='x', pady=2)
                tk.Label(row, text=cat, bg='white', fg=FG_PRIMARY,
                         font=self.font_normal, width=16,
                         anchor='w').pack(side='left')
                tk.Label(row, text=str(count), bg='white', fg=FG_SECONDARY,
                         font=self.font_small).pack(side='right')

        ttk.Button(pad, text="Close", style='Accent.TButton',
                   command=win.destroy).pack(pady=(20, 0), anchor='e')

    def on_closing(self):
        # One last config save before we vanish into the void.
        self._save_config()
        self.root.destroy()


#CLI
class TaskCLI:
    def __init__(self):
        self.manager = TaskManager()
        self.parser = self._create_parser()

    def _create_parser(self):
        # The command-line menu. Type "task --help" and bask in the options.
        parser = argparse.ArgumentParser(description='Task Manager')
        sub = parser.add_subparsers(dest='command')

        p = sub.add_parser('add')
        p.add_argument('title')
        p.add_argument('-d', '--description', default='')
        p.add_argument('-p', '--priority',
                       choices=['low', 'medium', 'high', 'urgent'],
                       default='medium')
        p.add_argument('-c', '--category', default='General')
        p.add_argument('--due', default=None)
        p.add_argument('-t', '--tags', default='')
        p.add_argument('-e', '--effort', type=int, default=0)

        p = sub.add_parser('list')
        p.add_argument('-s', '--status',
                       choices=['pending', 'in_progress',
                                'completed', 'archived'])
        p.add_argument('-c', '--category')
        p.add_argument('-p', '--priority',
                       choices=['low', 'medium', 'high', 'urgent'])
        p.add_argument('--search')
        p.add_argument('--overdue', action='store_true')

        p = sub.add_parser('update')
        p.add_argument('task_id')
        p.add_argument('--title')
        p.add_argument('--description')
        p.add_argument('--priority',
                       choices=['low', 'medium', 'high', 'urgent'])
        p.add_argument('--category')
        p.add_argument('--due')
        p.add_argument('--status',
                       choices=['pending', 'in_progress',
                                'completed', 'archived'])
        p.add_argument('--tags')
        p.add_argument('--effort', type=int)

        p = sub.add_parser('delete')
        p.add_argument('task_id')

        sub.add_parser('stats')
        sub.add_parser('gui')

        p = sub.add_parser('clear')
        p.add_argument('--force', action='store_true')

        return parser

    def _format_task(self, task, index=-1):
        # Pretty-print a task for the terminal. No colour codes. We tried
        # that once and half the terminals sulked.
        prefix = f"{index + 1}. " if index >= 0 else ""
        lines = [f"{prefix}{task.title}",
                 f"   ID: {task.task_id}   [{task.status}]   "
                 f"Priority: {task.priority}"]
        if task.category != 'General':
            lines.append(f"   Category: {task.category}")
        if task.tags:
            lines.append(f"   Tags: {', '.join(task.tags)}")
        if task.due_date:
            mark = " (OVERDUE)" if task.is_overdue() else ""
            lines.append(
                f"   Due: {task.due_date.strftime('%Y-%m-%d %H:%M')}{mark}")
        if task.description:
            lines.append(f"   {task.description}")
        return '\n'.join(lines)

    def run(self, args=None):
        args = self.parser.parse_args(args)
        if not args.command:
            self.parser.print_help()
            return

        if args.command == 'gui':
            # Pretend to be a normal CLI for one moment, then launch the GUI.
            root = tk.Tk()
            app = KanbanGUI(root)
            root.protocol("WM_DELETE_WINDOW", app.on_closing)
            root.mainloop()
            return

        if args.command == 'add':
            due = None
            if args.due:
                try:
                    due = parse_natural_date(args.due)
                except ValueError as e:
                    print(f"Error: {e}")
                    return
            tags = [t.strip() for t in args.tags.split(',') if t.strip()]
            task = Task(title=args.title, description=args.description,
                        priority=Priority.from_string(args.priority),
                        category=args.category, due_date=due,
                        tags=tags, effort=args.effort)
            print(f"Task added: {self.manager.add_task(task)}")

        elif args.command == 'list':
            status = (TaskStatus.from_string(args.status)
                      if args.status else None)
            priority = (Priority.from_string(args.priority)
                        if args.priority else None)
            if args.overdue:
                tasks = self.manager.get_overdue_tasks()
            else:
                tasks = self.manager.list_tasks(
                    status=status, category=args.category,
                    priority=priority, search=args.search)
            if not tasks:
                print("No tasks found.")
                return
            print(f"\n{len(tasks)} task(s):\n")
            for i, t in enumerate(tasks):
                print(self._format_task(t, i))
                print()

        elif args.command == 'update':
            # Collect only the fields that were actually given. The rest
            # stay untouched, which is the whole point of "update".
            updates = {}
            if args.title: updates['title'] = args.title
            if args.description: updates['description'] = args.description
            if args.priority:
                updates['priority'] = Priority.from_string(args.priority)
            if args.category: updates['category'] = args.category
            if args.due:
                try:
                    updates['due_date'] = parse_natural_date(args.due)
                except ValueError as e:
                    print(f"Error: {e}")
                    return
            if args.status:
                updates['status'] = TaskStatus.from_string(args.status)
            if args.tags:
                updates['tags'] = [t.strip()
                                   for t in args.tags.split(',') if t.strip()]
            if args.effort is not None:
                updates['effort'] = args.effort
            if not updates:
                print("No updates specified.")
                return
            if self.manager.update_task(args.task_id, **updates):
                print(f"Updated: {args.task_id}")
            else:
                print(f"Not found: {args.task_id}")

        elif args.command == 'delete':
            if self.manager.delete_task(args.task_id):
                print(f"Deleted: {args.task_id}")
            else:
                print(f"Not found: {args.task_id}")

        elif args.command == 'stats':
            s = self.manager.get_statistics()
            print(f"\nTotal: {s['total']}  Done: {s['completed']}  "
                  f"In progress: {s['in_progress']}  Pending: {s['pending']}  "
                  f"Overdue: {s['overdue']}  "
                  f"Rate: {s['completion_rate']:.1f}%\n")

        elif args.command == 'clear':
            # Nuke everything. Optional --force skips the stern question.
            if not args.force:
                if input(f"Delete all {len(self.manager.tasks)} tasks? "
                         "(y/N): ").lower() != 'y':
                    print("Cancelled.")
                    return
            n = len(self.manager.tasks)
            self.manager.tasks.clear()
            self.manager.save_tasks()
            print(f"Cleared {n} tasks.")


def main():
    # No arguments? Assume the user wants the pretty version and open the
    # GUI. Arguments? Hand over to the CLI and stay out of the way.
    if len(sys.argv) == 1:
        try:
            root = tk.Tk()
            app = KanbanGUI(root)
            root.protocol("WM_DELETE_WINDOW", app.on_closing)
            root.mainloop()
        except Exception as e:
            print(f"Error starting GUI: {e}")
            print("Make sure tkinter is installed.")
        return

    cli = TaskCLI()
    try:
        cli.run()
    except KeyboardInterrupt:
        print("\nCancelled.")
        sys.exit(1)


if __name__ == '__main__':
    main()
