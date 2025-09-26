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
                FOREIGN KEY (task_id) REFERENCES tasks (id)
            )
        ''')
        
        conn.commit()
        conn.close()
    
    def add_task(self, title, description, priority, deadline, estimated_duration=60):
        """Add a new task to the database and priority heap"""
        conn = sqlite3.connect('scheduler.db')
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO tasks (title, description, priority, deadline, estimated_duration)
            VALUES (?, ?, ?, ?, ?)
        ''', (title, description, priority, deadline, estimated_duration))
        
        task_id = cursor.lastrowid
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
        """Schedule notification for task deadline"""
        # Schedule notification 1 hour before deadline
        notification_time = deadline_dt - timedelta(hours=1)
        
        if notification_time > datetime.now():
            scheduler.add_job(
                func=self.send_notification,
                trigger=DateTrigger(run_date=notification_time),
                args=[task_id],
                id=f'notification_{task_id}',
                replace_existing=True
            )
    
    def send_notification(self, task_id):
        """Send notification for upcoming deadline"""
        conn = sqlite3.connect('scheduler.db')
        cursor = conn.cursor()
        
        cursor.execute('SELECT title, deadline FROM tasks WHERE id = ?', (task_id,))
        task = cursor.fetchone()
        
        if task:
            message = f"Reminder: Task '{task[0]}' is due soon (deadline: {task[1]})"
            cursor.execute(
                'INSERT INTO notifications (task_id, message) VALUES (?, ?)',
                (task_id, message)
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
            'estimated_duration': task[8]
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
        
        task_id = task_scheduler.add_task(title, description, priority, deadline, estimated_duration)
        flash(f'Task "{title}" added successfully!', 'success')
        return redirect(url_for('index'))
    
    return render_template('add_task.html')

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

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)