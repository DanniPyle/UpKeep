// Configuration
const API_BASE_URL = ''; // Same-origin when SPA is served by Flask

// State management
let currentUser = null;
let authToken = null;

// DOM elements
const authSection = document.getElementById('auth-section');
const dashboardSection = document.getElementById('dashboard-section');
const questionnaireSection = document.getElementById('questionnaire-section');
const flashMessages = document.getElementById('flash-messages');

// Initialize app
document.addEventListener('DOMContentLoaded', function() {
    initializeApp();
    setupEventListeners();
});

function initializeApp() {
    // Check for stored auth token
    authToken = localStorage.getItem('authToken');
    currentUser = JSON.parse(localStorage.getItem('currentUser') || 'null');
    
    if (authToken && currentUser) {
        showDashboard();
        loadDashboardData();
    } else {
        showAuthSection();
    }
}

function setupEventListeners() {
    // Auth tabs
    document.getElementById('login-tab').addEventListener('click', () => showLoginForm());
    document.getElementById('register-tab').addEventListener('click', () => showRegisterForm());
    
    // Auth forms
    document.getElementById('login-form').addEventListener('submit', handleLogin);
    document.getElementById('register-form').addEventListener('submit', handleRegister);
    
    // Navigation
    document.getElementById('questionnaire-btn').addEventListener('click', showQuestionnaire);
    document.getElementById('back-to-dashboard').addEventListener('click', showDashboard);
    document.getElementById('logout-btn').addEventListener('click', handleLogout);
    document.getElementById('logout-btn-2').addEventListener('click', handleLogout);
    
    // Questionnaire
    document.getElementById('questionnaire-form').addEventListener('submit', handleQuestionnaire);
}

// Auth functions
function showLoginForm() {
    document.getElementById('login-tab').classList.add('active');
    document.getElementById('register-tab').classList.remove('active');
    document.getElementById('login-form').style.display = 'block';
    document.getElementById('register-form').style.display = 'none';
}

function showRegisterForm() {
    document.getElementById('register-tab').classList.add('active');
    document.getElementById('login-tab').classList.remove('active');
    document.getElementById('register-form').style.display = 'block';
    document.getElementById('login-form').style.display = 'none';
}

async function handleLogin(e) {
    e.preventDefault();
    const username = document.getElementById('login-username').value;
    const password = document.getElementById('login-password').value;
    
    try {
        const response = await fetch(`${API_BASE_URL}/api/login`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ username, password })
        });
        
        const data = await response.json();
        
        if (response.ok) {
            authToken = data.token;
            currentUser = data.user;
            localStorage.setItem('authToken', authToken);
            localStorage.setItem('currentUser', JSON.stringify(currentUser));
            
            showFlashMessage('Login successful!');
            showDashboard();
            loadDashboardData();
        } else {
            showFlashMessage(data.error || 'Login failed', 'error');
        }
    } catch (error) {
        showFlashMessage('Network error. Please try again.', 'error');
    }
}

async function handleRegister(e) {
    e.preventDefault();
    const username = document.getElementById('register-username').value;
    const email = document.getElementById('register-email').value;
    const password = document.getElementById('register-password').value;
    
    try {
        const response = await fetch(`${API_BASE_URL}/api/register`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ username, email, password })
        });
        
        const data = await response.json();
        
        if (response.ok) {
            authToken = data.token;
            currentUser = data.user;
            localStorage.setItem('authToken', authToken);
            localStorage.setItem('currentUser', JSON.stringify(currentUser));
            
            showFlashMessage('Registration successful!');
            showQuestionnaire(); // Show questionnaire for new users
        } else {
            showFlashMessage(data.error || 'Registration failed', 'error');
        }
    } catch (error) {
        showFlashMessage('Network error. Please try again.', 'error');
    }
}

function handleLogout() {
    authToken = null;
    currentUser = null;
    localStorage.removeItem('authToken');
    localStorage.removeItem('currentUser');
    showAuthSection();
    showFlashMessage('Logged out successfully');
}

// Navigation functions
function showAuthSection() {
    authSection.style.display = 'block';
    dashboardSection.style.display = 'none';
    questionnaireSection.style.display = 'none';
}

function showDashboard() {
    authSection.style.display = 'none';
    dashboardSection.style.display = 'block';
    questionnaireSection.style.display = 'none';
    
    if (currentUser) {
        document.getElementById('welcome-message').textContent = `Welcome, ${currentUser.username}!`;
    }
}

function showQuestionnaire() {
    authSection.style.display = 'none';
    dashboardSection.style.display = 'none';
    questionnaireSection.style.display = 'block';
    loadQuestionnaireData();
}

// Dashboard functions
async function loadDashboardData() {
    try {
        const response = await fetch(`${API_BASE_URL}/api/dashboard`, {
            headers: {
                'Authorization': `Bearer ${authToken}`
            }
        });
        
        const data = await response.json();
        
        if (response.ok) {
            renderTasks(data);
        } else {
            showFlashMessage('Failed to load dashboard data', 'error');
        }
    } catch (error) {
        showFlashMessage('Network error loading dashboard', 'error');
    }
}

function renderTasks(data) {
    renderTaskSection('overdue-tasks', data.overdue_tasks, 'overdue');
    renderTaskSection('upcoming-tasks', data.upcoming_tasks, 'upcoming');
    renderTaskSection('future-tasks', data.future_tasks, 'future');
    renderTaskSection('completed-tasks', data.completed_tasks, 'completed');
}

function renderTaskSection(containerId, tasks, taskType) {
    const container = document.getElementById(containerId);
    
    if (!tasks || tasks.length === 0) {
        container.innerHTML = '<p>No tasks in this category.</p>';
        return;
    }
    
    container.innerHTML = tasks.map(task => `
        <div class="task ${taskType}">
            <div class="task-content">
                <div class="task-title">${task.title}</div>
                <div class="task-description">${task.description}</div>
                <div class="task-date">Due: ${formatDate(task.next_due_date)}</div>
            </div>
            <div class="task-actions">
                ${taskType === 'completed' 
                    ? `<button class="reset-btn" onclick="resetTask(${task.id})">Reset</button>`
                    : `<button class="complete-btn" onclick="completeTask(${task.id})">Complete</button>`
                }
            </div>
        </div>
    `).join('');
}

async function completeTask(taskId) {
    try {
        const response = await fetch(`${API_BASE_URL}/api/complete_task/${taskId}`, {
            method: 'POST',
            headers: {
                'Authorization': `Bearer ${authToken}`
            }
        });
        
        const data = await response.json();
        
        if (response.ok) {
            showFlashMessage('Task completed!');
            loadDashboardData();
        } else {
            showFlashMessage(data.error || 'Failed to complete task', 'error');
        }
    } catch (error) {
        showFlashMessage('Network error', 'error');
    }
}

async function resetTask(taskId) {
    try {
        const response = await fetch(`${API_BASE_URL}/api/reset_task/${taskId}`, {
            method: 'POST',
            headers: {
                'Authorization': `Bearer ${authToken}`
            }
        });
        
        const data = await response.json();
        
        if (response.ok) {
            showFlashMessage('Task reset!');
            loadDashboardData();
        } else {
            showFlashMessage(data.error || 'Failed to reset task', 'error');
        }
    } catch (error) {
        showFlashMessage('Network error', 'error');
    }
}

// Questionnaire functions
async function loadQuestionnaireData() {
    try {
        const response = await fetch(`${API_BASE_URL}/api/home_features`, {
            headers: {
                'Authorization': `Bearer ${authToken}`
            }
        });
        
        if (response.ok) {
            const data = await response.json();
            populateQuestionnaire(data.features);
        }
    } catch (error) {
        console.log('No existing features found');
    }
}

function populateQuestionnaire(features) {
    if (features) {
        Object.keys(features).forEach(feature => {
            const checkbox = document.getElementById(feature);
            if (checkbox) {
                checkbox.checked = features[feature];
            }
        });
    }
}

async function handleQuestionnaire(e) {
    e.preventDefault();
    
    const features = {
        has_hvac: document.getElementById('has_hvac').checked,
        has_gutters: document.getElementById('has_gutters').checked,
        has_dishwasher: document.getElementById('has_dishwasher').checked,
        has_smoke_detectors: document.getElementById('has_smoke_detectors').checked,
        has_water_heater: document.getElementById('has_water_heater').checked
    };
    
    try {
        const response = await fetch(`${API_BASE_URL}/api/questionnaire`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${authToken}`
            },
            body: JSON.stringify(features)
        });
        
        const data = await response.json();
        
        if (response.ok) {
            showFlashMessage('Home features saved and tasks generated!');
            showDashboard();
            loadDashboardData();
        } else {
            showFlashMessage(data.error || 'Failed to save features', 'error');
        }
    } catch (error) {
        showFlashMessage('Network error', 'error');
    }
}

// Utility functions
function showFlashMessage(message, type = 'success') {
    const messageDiv = document.createElement('div');
    messageDiv.className = `flash-message ${type}`;
    messageDiv.textContent = message;
    
    flashMessages.appendChild(messageDiv);
    
    setTimeout(() => {
        messageDiv.remove();
    }, 5000);
}

function formatDate(dateString) {
    const date = new Date(dateString);
    return date.toLocaleDateString();
}
