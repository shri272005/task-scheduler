from flask import Flask, render_template, request, jsonify, redirect, url_for, flash
from datetime import datetime, timedelta
import sqlite3
import json
import heapq
import networkx as nx
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.date import DateTrigger
import plotly.graph_objs as go
import plotly.utils
import os
import atexit

app = Flask(__name__)
app.secret_key = os.environ.get('SESSION_SECRET', 'dev-secret-key')

# Initialize scheduler
scheduler = BackgroundScheduler()
scheduler.start()

# Shutdown scheduler when app exits
atexit.register(lambda: scheduler.shutdown())

class TaskScheduler:
    def __init__(self):
        self.task_heap = []
        self.dependency_graph = nx.DiGraph()
        self.init_db()
    
    def init_db(self):
        """Initialize SQLite database with required tables"""
        conn = sqlite3.connect('scheduler.db')
        cursor = conn.cursor()
        
        # Tasks table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                description TEXT,
                priority INTEGER DEFAULT 1,
                deadline TEXT,
                status TEXT DEFAULT 'pending',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                completed_at TEXT,
                estimated_duration INTEGER DEFAULT 60
            )
        ''')
        
        # Task dependencies table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS task_dependencies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER,
                depends_on_task_id INTEGER,
                FOREIGN KEY (task_id) REFERENCES tasks (id),
                FOREIGN KEY (depends_on_task_id) REFERENCES tasks (id)
            )
        ''')
        
        # Notifications/alerts table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER,
                message TEXT,
                sent_at TEXT DEFAULT CURRENT_TIMESTAMP,
                read INTEGER DEFAULT 0,
                FOREIGN KEY (task_id) REFERENCES tasks (id)
            )
        ''')
        
        # Add 'read' column to existing notifications table if it doesn't exist
        cursor.execute("PRAGMA table_info(notifications)")
        columns = [column[1] for column in cursor.fetchall()]
        if 'read' not in columns:
            cursor.execute('ALTER TABLE notifications ADD COLUMN read INTEGER DEFAULT 0')
        
        conn.commit()
        conn.close()
    
    def add_task(self, title, description, priority, deadline, estimated_duration=60, dependencies=None):
        """Add a new task to the database and priority heap"""
        conn = sqlite3.connect('scheduler.db')
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO tasks (title, description, priority, deadline, estimated_duration)
            VALUES (?, ?, ?, ?, ?)
        ''', (title, description, priority, deadline, estimated_duration))
        
        task_id = cursor.lastrowid
        
        # Add dependencies if provided
        if dependencies:
            for dep_task_id in dependencies:
                cursor.execute('''
                    INSERT INTO task_dependencies (task_id, depends_on_task_id)
                    VALUES (?, ?)
                ''', (task_id, dep_task_id))
        
        conn.commit()
        conn.close()
        
        # Add to priority heap (negative priority for max heap behavior)
        deadline_dt = datetime.fromisoformat(deadline) if deadline else datetime.max
        heap_item = (-priority, deadline_dt, task_id, title)
        heapq.heappush(self.task_heap, heap_item)
        
        # Schedule deadline notification
        if deadline:
            self.schedule_notification(task_id, deadline_dt)
        
        return task_id
    
    def get_tasks_ordered(self):
        """Get tasks ordered by priority and dependencies using topological sort"""
        conn = sqlite3.connect('scheduler.db')
        cursor = conn.cursor()
        
        # Get all pending tasks
        cursor.execute('SELECT * FROM tasks WHERE status = "pending" ORDER BY priority DESC')
        tasks = cursor.fetchall()
        
        # Get dependencies
        cursor.execute('SELECT task_id, depends_on_task_id FROM task_dependencies')
        dependencies = cursor.fetchall()
        
        conn.close()
        
        # Build dependency graph
        self.dependency_graph.clear()
        for task in tasks:
            self.dependency_graph.add_node(task[0])  # task id
        
        for task_id, depends_on in dependencies:
            if task_id in self.dependency_graph.nodes and depends_on in self.dependency_graph.nodes:
                self.dependency_graph.add_edge(depends_on, task_id)
        
        # Get topologically sorted order
        try:
            sorted_order = list(nx.topological_sort(self.dependency_graph))
            # Sort tasks according to dependency order, then by priority
            task_dict = {task[0]: task for task in tasks}
            ordered_tasks = []
            
            for task_id in sorted_order:
                if task_id in task_dict:
                    ordered_tasks.append(task_dict[task_id])
            
            # Add any remaining tasks not in dependency graph
            for task in tasks:
                if task not in ordered_tasks:
                    ordered_tasks.append(task)
                    
            return ordered_tasks
            
        except nx.NetworkXError:
            # Circular dependency detected, return by priority only
            return tasks
    
    def schedule_notification(self, task_id, deadline_dt):
        """Schedule notifications for task deadline at multiple intervals"""
        now = datetime.now()
        
        # Schedule multiple notifications: 24 hours, 1 hour, and 5 minutes before deadline
        notification_intervals = [
            (timedelta(hours=24), "24 hours"),
            (timedelta(hours=1), "1 hour"), 
            (timedelta(minutes=5), "5 minutes")
        ]
        
        # For immediate testing: add a notification that triggers in 30 seconds
        immediate_notification_time = now + timedelta(seconds=30)
        if immediate_notification_time < deadline_dt:
            scheduler.add_job(
                func=self.send_notification,
                trigger=DateTrigger(run_date=immediate_notification_time),
                args=[task_id, "IMMEDIATE_TEST"],
                id=f'immediate_test_{task_id}',
                replace_existing=True
            )
        
        for interval, interval_name in notification_intervals:
            notification_time = deadline_dt - interval
            
            if notification_time > now:
                scheduler.add_job(
                    func=self.send_notification,
                    trigger=DateTrigger(run_date=notification_time),
                    args=[task_id, interval_name],
                    id=f'notification_{task_id}_{interval_name.replace(" ", "_")}',
                    replace_existing=True
                )
    
    def send_immediate_test_notification(self, task_id):
        """Send immediate test notification for demonstration"""
        conn = sqlite3.connect('scheduler.db')
        cursor = conn.cursor()
        
        cursor.execute('SELECT title, deadline FROM tasks WHERE id = ?', (task_id,))
        task = cursor.fetchone()
        
        if task:
            message = f"🔔 TEST ALERT: Task '{task[0]}' needs your attention! (Deadline: {task[1]})"
            cursor.execute(
                'INSERT INTO notifications (task_id, message, read) VALUES (?, ?, ?)',
                (task_id, message, 0)
            )
        
        conn.commit()
        conn.close()
    
    def send_notification(self, task_id, interval_name="1 hour"):
        """Send notification for upcoming deadline"""
        conn = sqlite3.connect('scheduler.db')
        cursor = conn.cursor()
        
        cursor.execute('SELECT title, deadline FROM tasks WHERE id = ?', (task_id,))
        task = cursor.fetchone()
        
        if task:
            message = f"⏰ {interval_name.upper()} REMINDER: Task '{task[0]}' deadline approaching! Due: {task[1]}"
            cursor.execute(
                'INSERT INTO notifications (task_id, message, read) VALUES (?, ?, ?)',
                (task_id, message, 0)
            )
        
        conn.commit()
        conn.close()
    
    def get_analytics(self):
        """Get productivity analytics data"""
        conn = sqlite3.connect('scheduler.db')
        cursor = conn.cursor()
        
        # Task completion stats
        cursor.execute('SELECT status, COUNT(*) FROM tasks GROUP BY status')
        status_counts = dict(cursor.fetchall())
        
        # Tasks by priority
        cursor.execute('SELECT priority, COUNT(*) FROM tasks GROUP BY priority')
        priority_counts = dict(cursor.fetchall())
        
        # Daily completion trend (last 7 days)
        cursor.execute('''
            SELECT DATE(completed_at) as date, COUNT(*) as completed
            FROM tasks 
            WHERE completed_at IS NOT NULL 
            AND DATE(completed_at) >= DATE('now', '-7 days')
            GROUP BY DATE(completed_at)
            ORDER BY date
        ''')
        daily_completions = cursor.fetchall()
        
        conn.close()
        
        return {
            'status_counts': status_counts,
            'priority_counts': priority_counts,
            'daily_completions': daily_completions
        }
    
    def get_task_dependencies(self, task_id):
        """Get list of tasks that this task depends on"""
        conn = sqlite3.connect('scheduler.db')
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT t.id, t.title, t.status
            FROM tasks t
            JOIN task_dependencies td ON t.id = td.depends_on_task_id
            WHERE td.task_id = ?
        ''', (task_id,))
        
        dependencies = cursor.fetchall()
        conn.close()
        
        return [{'id': dep[0], 'title': dep[1], 'status': dep[2]} for dep in dependencies]
    
    def get_recent_notifications(self, limit=10):
        """Get recent notifications"""
        conn = sqlite3.connect('scheduler.db')
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT n.id, n.message, n.sent_at, t.title, t.id as task_id, n.read
            FROM notifications n
            LEFT JOIN tasks t ON n.task_id = t.id
            ORDER BY n.sent_at DESC
            LIMIT ?
        ''', (limit,))
        
        notifications = cursor.fetchall()
        conn.close()
        
        return [{
            'id': notif[0],
            'message': notif[1],
            'sent_at': notif[2],
            'task_title': notif[3],
            'task_id': notif[4],
            'read': notif[5]
        } for notif in notifications]
    
    def mark_notification_read(self, notification_id):
        """Mark a notification as read"""
        conn = sqlite3.connect('scheduler.db')
        cursor = conn.cursor()
        
        cursor.execute('UPDATE notifications SET read = 1 WHERE id = ?', (notification_id,))
        conn.commit()
        conn.close()

# Initialize task scheduler
task_scheduler = TaskScheduler()

@app.route('/')
def index():
    """Main dashboard view"""
    tasks = task_scheduler.get_tasks_ordered()
    
    # Convert to list of dicts for template
    task_list = []
    for task in tasks:
        task_dict = {
            'id': task[0],
            'title': task[1],
            'description': task[2],
            'priority': task[3],
            'deadline': task[4],
            'status': task[5],
            'created_at': task[6],
            'completed_at': task[7],
            'estimated_duration': task[8],
            'dependencies': task_scheduler.get_task_dependencies(task[0])
        }
        task_list.append(task_dict)
    
    return render_template('index.html', tasks=task_list)

@app.route('/add_task', methods=['GET', 'POST'])
def add_task():
    """Add new task"""
    if request.method == 'POST':
        title = request.form['title']
        description = request.form['description']
        priority = int(request.form['priority'])
        deadline = request.form['deadline']
        estimated_duration = int(request.form.get('estimated_duration', 60))
        dependencies = request.form.getlist('dependencies')  # Get list of selected dependencies
        
        # Convert dependency strings to integers
        dep_ids = [int(dep_id) for dep_id in dependencies if dep_id.isdigit()]
        
        task_id = task_scheduler.add_task(title, description, priority, deadline, estimated_duration, dep_ids)
        flash(f'Task "{title}" added successfully!', 'success')
        return redirect(url_for('index'))
    
    # Get available tasks for dependencies selection
    conn = sqlite3.connect('scheduler.db')
    cursor = conn.cursor()
    cursor.execute('SELECT id, title, priority FROM tasks WHERE status != "completed" ORDER BY title')
    available_tasks = cursor.fetchall()
    conn.close()
    
    # Convert to list of dicts for template
    task_list = []
    for task in available_tasks:
        task_dict = {'id': task[0], 'title': task[1], 'priority': task[2]}
        task_list.append(task_dict)
    
    return render_template('add_task.html', available_tasks=task_list)

@app.route('/complete_task/<int:task_id>', methods=['POST'])
def complete_task(task_id):
    """Mark task as completed"""
    conn = sqlite3.connect('scheduler.db')
    cursor = conn.cursor()
    
    cursor.execute(
        'UPDATE tasks SET status = "completed", completed_at = CURRENT_TIMESTAMP WHERE id = ?',
        (task_id,)
    )
    
    conn.commit()
    conn.close()
    
    flash('Task marked as completed!', 'success')
    return redirect(url_for('index'))

@app.route('/analytics')
def analytics():
    """Analytics dashboard"""
    analytics_data = task_scheduler.get_analytics()
    
    # Create Plotly charts
    # Status distribution pie chart
    status_fig = go.Figure(data=[go.Pie(
        labels=list(analytics_data['status_counts'].keys()),
        values=list(analytics_data['status_counts'].values()),
        title="Task Status Distribution"
    )])
    
    # Daily completions line chart
    if analytics_data['daily_completions']:
        dates, completions = zip(*analytics_data['daily_completions'])
        completion_fig = go.Figure(data=[go.Scatter(
            x=dates,
            y=completions,
            mode='lines+markers',
            name='Completed Tasks'
        )])
        completion_fig.update_layout(title="Daily Task Completion Trend")
    else:
        completion_fig = go.Figure()
        completion_fig.update_layout(title="Daily Task Completion Trend (No Data)")
    
    # Priority distribution bar chart
    priority_fig = go.Figure(data=[go.Bar(
        x=list(analytics_data['priority_counts'].keys()),
        y=list(analytics_data['priority_counts'].values()),
        name='Tasks by Priority'
    )])
    priority_fig.update_layout(title="Tasks by Priority Level")
    
    # Convert to JSON for template
    charts_json = {
        'status_chart': json.dumps(status_fig, cls=plotly.utils.PlotlyJSONEncoder),
        'completion_chart': json.dumps(completion_fig, cls=plotly.utils.PlotlyJSONEncoder),
        'priority_chart': json.dumps(priority_fig, cls=plotly.utils.PlotlyJSONEncoder)
    }
    
    return render_template('analytics.html', charts=charts_json)

@app.route('/calendar')
def calendar():
    """Calendar view of tasks"""
    conn = sqlite3.connect('scheduler.db')
    cursor = conn.cursor()
    
    cursor.execute('SELECT * FROM tasks WHERE deadline IS NOT NULL ORDER BY deadline')
    tasks = cursor.fetchall()
    conn.close()
    
    # Create calendar timeline
    events = []
    for task in tasks:
        events.append({
            'x': task[4],  # deadline
            'y': task[1],  # title
            'text': f"Priority: {task[3]}<br>Status: {task[5]}",
            'mode': 'markers',
            'marker': {
                'size': 10,
                'color': 'red' if task[5] == 'pending' else 'green'
            }
        })
    
    calendar_fig = go.Figure()
    
    for event in events:
        calendar_fig.add_trace(go.Scatter(
            x=[event['x']],
            y=[event['y']],
            mode='markers+text',
            text=[event['y']],
            textposition='middle right',
            marker=event['marker'],
            showlegend=False,
            hovertext=event['text']
        ))
    
    calendar_fig.update_layout(
        title="Task Calendar Timeline",
        xaxis_title="Deadline",
        yaxis_title="Tasks",
        height=600
    )
    
    calendar_json = json.dumps(calendar_fig, cls=plotly.utils.PlotlyJSONEncoder)
    
    return render_template('calendar.html', calendar_chart=calendar_json)

@app.route('/notifications')
def notifications():
    """View notifications"""
    notifications = task_scheduler.get_recent_notifications(limit=20)
    return render_template('notifications.html', notifications=notifications)

@app.route('/mark_notification_read/<int:notification_id>', methods=['POST'])
def mark_notification_read(notification_id):
    """Mark notification as read"""
    task_scheduler.mark_notification_read(notification_id)
    return redirect(url_for('notifications'))

@app.route('/get_unread_count')
def get_unread_count():
    """Get count of unread notifications for AJAX"""
    conn = sqlite3.connect('scheduler.db')
    cursor = conn.cursor()
    cursor.execute('SELECT COUNT(*) FROM notifications WHERE read = 0')
    count = cursor.fetchone()[0]
    conn.close()
    return jsonify({'unread_count': count})

@app.route('/test_notification/<int:task_id>', methods=['POST'])
def test_notification(task_id):
    """Create immediate test notification for demonstration"""
    task_scheduler.send_immediate_test_notification(task_id)
    flash('Test notification sent!', 'success')
    return redirect(url_for('index'))

@app.route('/trigger_all_notifications', methods=['POST'])
def trigger_all_notifications():
    """Trigger test notifications for all pending tasks with deadlines"""
    conn = sqlite3.connect('scheduler.db')
    cursor = conn.cursor()
    cursor.execute('SELECT id FROM tasks WHERE status = "pending" AND deadline IS NOT NULL')
    task_ids = [row[0] for row in cursor.fetchall()]
    conn.close()
    
    for task_id in task_ids:
        task_scheduler.send_immediate_test_notification(task_id)
    
    flash(f'Test notifications sent for {len(task_ids)} tasks!', 'success')
    return redirect(url_for('notifications'))

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)