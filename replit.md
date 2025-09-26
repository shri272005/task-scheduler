# Smart Event & Task Scheduler

## Overview

A web-based task management and scheduling application built with Flask that provides intelligent task prioritization, dependency management, and productivity analytics. The system uses graph-based dependency tracking, priority-based scheduling algorithms, and automated notification systems to help users manage their tasks efficiently. Features include a visual dashboard, calendar timeline, analytics charts, and real-time notifications for deadlines and task dependencies.

## User Preferences

Preferred communication style: Simple, everyday language.

## System Architecture

### Frontend Architecture
- **Template Engine**: Jinja2 templates with Bootstrap 5 for responsive UI
- **JavaScript Libraries**: Plotly.js for interactive charts and data visualization
- **Styling**: Bootstrap CSS framework with Font Awesome icons and custom CSS for task priority indicators
- **User Interface**: Multi-page application with dashboard, task management, calendar view, and analytics

### Backend Architecture
- **Web Framework**: Flask with modular route handling
- **Task Scheduling**: Custom TaskScheduler class implementing priority-based heap data structure
- **Dependency Management**: NetworkX directed graph for task dependencies and topological sorting
- **Background Processing**: APScheduler for automated notifications and deadline monitoring
- **Session Management**: Flask sessions with configurable secret key

### Data Storage
- **Database**: SQLite with schema for tasks, dependencies, and notifications
- **Task Model**: Includes priority, deadlines, status tracking, estimated duration, and completion timestamps
- **Dependency Tracking**: Separate table for task relationships with foreign key constraints
- **Notification System**: Persistent storage for user alerts and read status

### Scheduling Algorithms
- **Priority Queue**: Min-heap implementation for task prioritization
- **Dependency Resolution**: Topological sorting to determine valid task execution order
- **Deadline Monitoring**: Automated background jobs to trigger time-based notifications
- **Conflict Detection**: Graph-based circular dependency detection

### Visualization Components
- **Analytics Dashboard**: Plotly charts for task distribution, priority analysis, and completion trends
- **Calendar Timeline**: Gantt-chart style visualization of task schedules and deadlines
- **Real-time Updates**: Dynamic badge updates for notification counts

## External Dependencies

### Python Libraries
- **Flask**: Web framework for routing and template rendering
- **SQLite3**: Built-in database connectivity
- **NetworkX**: Graph algorithms for dependency management
- **APScheduler**: Background task scheduling and cron-like functionality
- **Plotly**: Interactive charting and data visualization
- **Heapq**: Priority queue implementation for task scheduling

### Frontend Libraries
- **Bootstrap 5**: CSS framework via CDN
- **Font Awesome 6**: Icon library via CDN
- **Plotly.js**: JavaScript charting library via CDN

### System Dependencies
- **SQLite**: Local file-based database (no external database server required)
- **Environment Variables**: SESSION_SECRET for security configuration