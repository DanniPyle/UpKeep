// Lightweight MPA helpers only
const API_BASE_URL = '';
const isMpa = true; // Force MPA-only behavior
const flashMessages = document.getElementById('flash-messages');

// Loading state helpers
function showLoader(message = 'Loading...') {
    const loader = document.getElementById('global-loader');
    if (loader) {
        const text = loader.querySelector('.loader-text');
        if (text) text.textContent = message;
        loader.style.display = 'flex';
    }
}

function hideLoader() {
    const loader = document.getElementById('global-loader');
    if (loader) loader.style.display = 'none';
}

// Initialize app
document.addEventListener('DOMContentLoaded', function() {
    setupEventListeners();
    const heroGreeting = document.getElementById('hero-greeting');
    if (heroGreeting) heroGreeting.textContent = getTimeOfDayGreeting();
    
    // Auto-hide loader on page load
    hideLoader();
});

// Removed SPA initialization and auth token handling (MPA only)

// Helper: relative due label (e.g., "N days ago", "Today", or formatted date)
function getRelativeDueLabel(dateStr) {
    if (!dateStr) return '';
    const due = new Date(dateStr);
    const now = new Date();
    const isToday = due.getFullYear() === now.getFullYear() && due.getMonth() === now.getMonth() && due.getDate() === now.getDate();
    const diffDays = Math.ceil((now - due) / (1000 * 60 * 60 * 24));
    if (diffDays > 0) {
        return `${diffDays} ${diffDays === 1 ? 'day' : 'days'} ago`;
    }
    if (isToday) return 'Today';
    return formatDate(dateStr);
}

// Shared card component used by both renderUrgent and renderTaskSection
// options: { statusClass, dueLabel, isUrgent, taskType }
function frequencyLabel(days) {
    if (days == null || days === '') return '';
    const d = Number(days);
    if (!Number.isFinite(d) || d <= 0) return '';
    const map = new Map([
        [7, 'Weekly'],
        [14, 'Every 2 Weeks'],
        [21, 'Every 3 Weeks'],
        [28, 'Every 4 Weeks'],
        [30, 'Monthly'],
        [60, 'Every 2 Months'],
        [90, 'Quarterly'],
        [120, 'Every 4 Months'],
        [180, 'Every 6 Months'],
        [270, 'Every 9 Months'],
        [365, 'Yearly'],
        [730, 'Every 2 Years'],
        [1095, 'Every 3 Years'],
        [1825, 'Every 5 Years'],
    ]);
    if (map.has(d)) return map.get(d);
    if (d % 365 === 0) {
        const n = d / 365;
        return `Every ${n} Year${n !== 1 ? 's' : ''}`;
    }
    if (d % 30 === 0) {
        const n = d / 30;
        return n === 1 ? 'Monthly' : `Every ${n} Months`;
    }
    if (d % 7 === 0 && d <= 84) {
        const n = d / 7;
        return `Every ${n} Week${n !== 1 ? 's' : ''}`;
    }
    return `Every ${d} days`;
}

function buildTaskCard(task, options = {}) {
    const { statusClass = '', dueLabel = '', isUrgent = false, taskType = '' } = options;
    const priorityRaw = task.priority ? String(task.priority) : '';
    const priority = priorityRaw.toLowerCase();
    const freq = task.frequency_days ? frequencyLabel(task.frequency_days) : '';
    const headerClass = isUrgent ? 'urgent' : '';

    // Actions differ for completed vs other types
    let actionsHtml = '';
    if (taskType === 'completed') {
        actionsHtml = `
            <button class="reset-btn" onclick="resetTask(${task.id})">
              <svg class="icon" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 12a9 9 0 1 0 3-6.708"/><path d="M3 4v5h5"/></svg>
              Reset
            </button>`;
    } else if (isUrgent) {
        actionsHtml = `
            <button class="btn primary" onclick="completeTask(${task.id})">
              <svg class="icon" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 13l4 4L19 7"/></svg>
              Complete
            </button>
            <button class="btn ghost" onclick="openEditModal(${task.id})">
              <svg class="icon" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4Z"/></svg>
              Edit
            </button>
            <button class="btn ghost" onclick="viewHistory(${task.id})">
              <svg class="icon" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M3 3v5h5"/>
                <path d="M3.05 13a9 9 0 1 0 2.13-5.36"/>
                <path d="M12 7v5l3 3"/>
              </svg>
              History
            </button>`;
    } else {
        actionsHtml = `
            <button class="complete-btn" onclick="completeTask(${task.id})">
              <svg class="icon" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 13l4 4L19 7"/></svg>
              Complete
            </button>
            <button class="edit-btn ghost" onclick="openEditModal(${task.id})">
              <svg class="icon" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4Z"/></svg>
              Edit
            </button>
            <button class="history-btn ghost" onclick="viewHistory(${task.id})">
              <svg class="icon" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M3 3v5h5"/>
                <path d="M3.05 13a9 9 0 1 0 2.13-5.36"/>
                <path d="M12 7v5l3 3"/>
              </svg>
              History
            </button>`;
    }

    return `
      <div class="task-card ${statusClass}">
        <div class="card-header ${headerClass}">
          <div class="title">${task.title}</div>
          ${task.description ? `<div class="desc">${task.description}</div>` : ''}
          <a class="corner-dot" href="/task/${task.id}" title="View details">
            <svg class="icon" aria-hidden="true"><use href="#icon-info"></use></svg>
          </a>
        </div>
        <div class="card-body">
          <div class="info">  
            <div class="info-item"><span class="label">Due date</span><span class="value">${dueLabel || '-'}</span></div>
            <div class="info-item"><span class="label">Priority</span><span class="value"><span class="pill ${priority || ''}">${priorityRaw || '-'}</span></span></div>
            <div class="info-item"><span class="label">Frequency</span><span class="value"><span class="badge freq">${freq || '-'}</span></span></div>
          </div>
          <div class="actions">
            ${actionsHtml}
          </div>
        </div>
      </div>`;
}

async function snoozeTaskQuick(taskId, days) {
    try {
        const response = await fetch(`${API_BASE_URL}/api/snooze_task/${taskId}`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${authToken}`
            },
            body: JSON.stringify({ days })
        });
        const data = await response.json();
        if (response.ok) {
            showFlashMessage(data.message || `Snoozed ${days} days`);
            loadDashboardData();
        } else {
            showFlashMessage(data.error || 'Failed to snooze task', 'error');
        }
    } catch (e) {
        showFlashMessage('Network error', 'error');
    }
}

function renderUrgent(data) {
    const sec = document.getElementById('urgent');
    const card = document.getElementById('urgent-card');
    if (!sec || !card) return;
    const list = data.overdue_tasks || [];
    if (!list.length) {
        // Empty state keeps the right column visible
        card.innerHTML = `
          <div class="card">
            <div class="text">
              <div class="title">You're all caught up</div>
              <div class="subtitle">No overdue tasks right now. Great job!</div>
            </div>
          </div>`;
        return;
    }
    const t = list[0]; // top overdue already sorted by API
    // Ensure urgent task is available for Edit modal
    if (t && t.id) { tasksCache[t.id] = t; }
    const dueLabel = getRelativeDueLabel(t.next_due_date);
    card.innerHTML = buildTaskCard(t, { statusClass: 'urgent', dueLabel, isUrgent: true, taskType: 'overdue' });
}



async function snoozeTask(taskId) {
    const daysStr = prompt('Snooze by how many days?');
    if (!daysStr) return;
    const days = parseInt(daysStr, 10);
    if (isNaN(days) || days <= 0) {
        showFlashMessage('Please enter a positive number of days', 'error');
        return;
    }
    try {
        const response = await fetch(`${API_BASE_URL}/api/snooze_task/${taskId}`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${authToken}`
            },
            body: JSON.stringify({ days })
        });
        const data = await response.json();
        if (response.ok) {
            showFlashMessage(data.message || 'Task snoozed');
            loadDashboardData();
        } else {
            showFlashMessage(data.error || 'Failed to snooze task', 'error');
        }
    } catch (e) {
        showFlashMessage('Network error', 'error');
    }
}
// CSV import UI removed

// Validation helpers
function clearEditValidation() {
    const titleEl = document.getElementById('edit-title');
    const freqEl = document.getElementById('edit-frequency');
    const titleErr = document.getElementById('edit-title-error');
    const freqErr = document.getElementById('edit-frequency-error');
    [titleEl, freqEl].forEach(el => el && el.classList.remove('invalid'));
    if (titleErr) titleErr.textContent = '';
    if (freqErr) freqErr.textContent = '';
}

function validateEditForm() {
    const titleEl = document.getElementById('edit-title');
    const freqEl = document.getElementById('edit-frequency');
    const titleErr = document.getElementById('edit-title-error');
    const freqErr = document.getElementById('edit-frequency-error');
    let valid = true;

    // Title validation
    if (!titleEl.value.trim()) {
        valid = false;
        titleEl.classList.add('invalid');
        if (titleErr) titleErr.textContent = 'Title is required.';
    } else {
        titleEl.classList.remove('invalid');
        if (titleErr) titleErr.textContent = '';
    }

    // Frequency validation
    const freq = parseInt(freqEl.value, 10);
    if (!freq || freq <= 0) {
        valid = false;
        freqEl.classList.add('invalid');
        if (freqErr) freqErr.textContent = 'Enter a positive number of days.';
    } else {
        freqEl.classList.remove('invalid');
        if (freqErr) freqErr.textContent = '';
    }

    return valid;
}

async function viewHistory(taskId) {
    try {
        const response = await fetch(`${API_BASE_URL}/api/task_history/${taskId}`, {
            headers: { 'Authorization': `Bearer ${authToken}` }
        });
        const data = await response.json();
        if (response.ok) {
            openHistoryModal(data.history || []);
        } else {
            showFlashMessage(data.error || 'Failed to load history', 'error');
        }
    } catch (e) {
        showFlashMessage('Network error', 'error');
    }
}

function openHistoryModal(history) {
    const modal = document.getElementById('history-modal');
    const body = document.getElementById('history-body');
    if (!modal || !body) return;
    if (!history.length) {
        body.innerHTML = '<p>No history yet.</p>';
    } else {
        body.innerHTML = history.map(h => `
            <div class="hist-row">
                <span class="hist-time">${formatDate(h.created_at)}</span>
                <span class="hist-action">${h.action}</span>
                ${h.delta_days ? `<span class="hist-delta">${h.delta_days} days</span>` : ''}
            </div>
        `).join('');
    }
    modal.style.display = 'flex';
}

function closeHistoryModal() {
    const modal = document.getElementById('history-modal');
    if (modal) modal.style.display = 'none';
}

function setupEventListeners() {
    // Treat any server-rendered page (no #auth-section) as MPA
    const isMpa = !document.getElementById('auth-section');
    
    // Add loading state to all task completion links
    document.querySelectorAll('a[href*="/complete/"]').forEach(link => {
        link.addEventListener('click', function(e) {
            showLoader('Completing task...');
        });
    });
    
    // Add loading state to navigation links that load new pages
    document.querySelectorAll('a.btn, a.quick-btn').forEach(link => {
        if (link.href && !link.href.includes('#') && !link.target) {
            link.addEventListener('click', function(e) {
                if (!e.ctrlKey && !e.metaKey) {
                    showLoader('Loading...');
                }
            });
        }
    });
    
    // Auth tabs (SPA only)
    const loginTab = document.getElementById('login-tab');
    const registerTab = document.getElementById('register-tab');
    if (loginTab) loginTab.addEventListener('click', () => showLoginForm());
    if (registerTab) registerTab.addEventListener('click', () => showRegisterForm());
    
    // Auth forms (SPA only)
    const loginForm = document.getElementById('login-form');
    const registerForm = document.getElementById('register-form');
    if (loginForm) loginForm.addEventListener('submit', handleLogin);
    if (registerForm) registerForm.addEventListener('submit', handleRegister);
    
    // Navigation
    const questionnaireBtn = document.getElementById('questionnaire-btn');
    const backToDashboardBtn = document.getElementById('back-to-dashboard');
    const logoutBtn = document.getElementById('logout-btn');
    const logoutBtn2 = document.getElementById('logout-btn-2');
    if (questionnaireBtn) questionnaireBtn.addEventListener('click', showQuestionnaire);
    if (backToDashboardBtn) backToDashboardBtn.addEventListener('click', showDashboard);
    if (logoutBtn) logoutBtn.addEventListener('click', handleLogout);
    if (logoutBtn2) logoutBtn2.addEventListener('click', handleLogout);

    // User menu (avatar dropdown)
    const userMenuToggle = document.getElementById('user-menu-toggle');
    const userMenu = document.getElementById('user-menu');
    if (userMenuToggle && userMenu) {
        const closeMenu = () => {
            userMenu.classList.remove('open');
            userMenuToggle.setAttribute('aria-expanded', 'false');
        };
        const openMenu = () => {
            userMenu.classList.add('open');
            userMenuToggle.setAttribute('aria-expanded', 'true');
        };
        userMenuToggle.addEventListener('click', (e) => {
            e.stopPropagation();
            const isOpen = userMenu.classList.contains('open');
            if (isOpen) closeMenu(); else openMenu();
        });
        // Click outside closes
        document.addEventListener('click', (e) => {
            if (!userMenu.contains(e.target) && e.target !== userMenuToggle) {
                closeMenu();
            }
        });
        // Esc closes
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') closeMenu();
        });
        // Prevent clicks inside the menu from bubbling (so it won't close immediately)
        userMenu.addEventListener('click', (e) => e.stopPropagation());
    }
    
    // Questionnaire: only intercept in SPA mode; let normal form POST in MPA
    const questionnaireForm = document.getElementById('questionnaire-form');
    if (questionnaireForm && !isMpa) {
        questionnaireForm.addEventListener('submit', handleQuestionnaire);
    }

    // Filters: Disable API-bound filters in MPA to avoid token-required endpoints
    if (!isMpa) {
        const applyBtn = document.getElementById('apply-filters');
        const clearBtn = document.getElementById('clear-filters');
        const filterSearch = document.getElementById('filter-search');
        const heroSearch = document.getElementById('hero-search');
        const heroSearchForm = document.getElementById('hero-search-form');
        // Debounce helper for live filtering
        const debounce = (fn, delay = 300) => {
            let t;
            return (...args) => {
                clearTimeout(t);
                t = setTimeout(() => fn.apply(null, args), delay);
            };
        };
        const debouncedLoad = debounce(() => loadDashboardData(), 300);
        // Keep hero search and filter search in sync
        if (heroSearch && filterSearch) {
            // Initialize hero search with existing filter value
            heroSearch.value = filterSearch.value || '';
            heroSearch.addEventListener('input', () => {
                filterSearch.value = heroSearch.value;
                debouncedLoad();
            });
            heroSearch.addEventListener('keydown', (e) => {
                if (e.key === 'Enter') {
                    e.preventDefault();
                    loadDashboardData();
                }
            });
            if (heroSearchForm) {
                heroSearchForm.addEventListener('submit', (e) => {
                    e.preventDefault();
                    loadDashboardData();
                });
            }
        }
        // Typing in sidebar search should also live-filter and sync hero
        if (filterSearch) {
            filterSearch.addEventListener('input', () => {
                if (heroSearch) heroSearch.value = filterSearch.value;
                debouncedLoad();
            });
            filterSearch.addEventListener('keydown', (e) => {
                if (e.key === 'Enter') {
                    e.preventDefault();
                    loadDashboardData();
                }
            });
        }
        // Advanced filters live updates
        ['filter-category','filter-priority','filter-min-freq','filter-max-freq'].forEach(id => {
            const el = document.getElementById(id);
            if (!el) return;
            el.addEventListener('input', debouncedLoad);
            el.addEventListener('change', debouncedLoad);
        });
        if (applyBtn) {
            applyBtn.addEventListener('click', () => {
                loadDashboardData();
            });
        }
        if (clearBtn) {
            clearBtn.addEventListener('click', () => {
                document.getElementById('filter-search').value = '';
                if (heroSearch) heroSearch.value = '';
                const cat = document.getElementById('filter-category');
                const pri = document.getElementById('filter-priority');
                const minF = document.getElementById('filter-min-freq');
                const maxF = document.getElementById('filter-max-freq');
                if (cat) cat.value = '';
                if (pri) pri.value = '';
                if (minF) minF.value = '';
                if (maxF) maxF.value = '';
                loadDashboardData();
            });
        }
    }

    // History modal
    const closeHistory = document.getElementById('close-history');
    if (closeHistory) {
        closeHistory.addEventListener('click', closeHistoryModal);
    }
    const historyModal = document.getElementById('history-modal');
    if (historyModal) {
        historyModal.addEventListener('click', (e) => {
            if (e.target === historyModal) closeHistoryModal();
        });
    }

    // Edit modal
    const editCancel = document.getElementById('edit-cancel');
    const editSave = document.getElementById('edit-save');
    if (editCancel) editCancel.addEventListener('click', closeEditModal);
    if (editSave) editSave.addEventListener('click', saveEditTask);
    const editModal = document.getElementById('edit-modal');
    if (editModal) {
        editModal.addEventListener('click', (e) => {
            if (e.target === editModal) closeEditModal();
        });
    }

    // CSV import UI removed

    // Edit form inline validation
    const editTitle = document.getElementById('edit-title');
    const editFrequency = document.getElementById('edit-frequency');
    if (editTitle) editTitle.addEventListener('input', validateEditForm);
    if (editFrequency) editFrequency.addEventListener('input', validateEditForm);

    // Global ESC key to close modals
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            closeHistoryModal();
            closeEditModal();
        }
    });

    // Delegated handler for flash close buttons (server-rendered and JS-added)
    document.addEventListener('click', (e) => {
        const btn = e.target.closest('.flash-close');
        if (!btn) return;
        const msg = btn.closest('.flash-message');
        if (msg) msg.remove();
    });
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
    
    // welcome-message removed from layout

    // Hero greeting + name
    const heroGreeting = document.getElementById('hero-greeting');
    const heroName = document.getElementById('hero-name');
    if (heroGreeting) heroGreeting.textContent = getTimeOfDayGreeting();
    if (heroName && currentUser && currentUser.username) heroName.textContent = currentUser.username;
    // Set avatar initial
    const avatarInitial = document.getElementById('avatar-initial');
    if (avatarInitial && currentUser && currentUser.username) {
        avatarInitial.textContent = (currentUser.username[0] || 'U').toUpperCase();
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
        // Build query params from filters
        const params = new URLSearchParams();
        const q = document.getElementById('filter-search');
        const cat = document.getElementById('filter-category');
        const pri = document.getElementById('filter-priority');
        const minF = document.getElementById('filter-min-freq');
        const maxF = document.getElementById('filter-max-freq');
        if (q && q.value) params.set('search', q.value);
        if (cat && cat.value) params.set('category', cat.value);
        if (pri && pri.value) params.set('priority', pri.value);
        if (minF && minF.value) params.set('min_freq', minF.value);
        if (maxF && maxF.value) params.set('max_freq', maxF.value);

        const response = await fetch(`${API_BASE_URL}/api/dashboard${params.toString() ? `?${params.toString()}` : ''}` , {
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
    renderOverview(data);
    // Urgent shows the top overdue task (if any)
    renderUrgent(data);

    // Overdue section should exclude the urgent task
    const overdueAll = (data.overdue_tasks || []);
    const overdueRemainder = overdueAll.slice(1); // hide the top one shown in Urgent
    renderTaskSection('overdue-tasks', overdueRemainder, 'overdue');
    renderTaskSection('upcoming-tasks', data.upcoming_tasks, 'upcoming');
    renderTaskSection('future-tasks', data.future_tasks, 'future');
    renderTaskSection('completed-tasks', data.completed_tasks, 'completed');
}

function renderOverview(data) {
    const wrap = document.getElementById('overview-tiles');
    if (!wrap) return;

    const today = new Date();
    const endOfWeek = new Date(today); // 7 days window for "due this week"
    endOfWeek.setDate(endOfWeek.getDate() + 7);

    const overdueCount = (data.overdue_tasks || []).length;
    const dueThisWeek = (data.upcoming_tasks || []).filter(t => {
        if (!t.next_due_date) return false;
        const d = new Date(t.next_due_date);
        return d <= endOfWeek;
    }).length;

    // Completed this month
    const now = new Date();
    const m = now.getMonth();
    const y = now.getFullYear();
    const completedThisMonth = (data.completed_tasks || []).filter(t => {
        if (!t.last_completed) return false;
        const d = new Date(t.last_completed);
        return d.getMonth() === m && d.getFullYear() === y;
    }).length;

    // Upcoming total (next 30 days already in API as upcoming_tasks)
    const upcomingCount = (data.upcoming_tasks || []).length;

    wrap.innerHTML = `
      <div class="tile overdue">
        <div class="label">Overdue</div>
        <div class="value">${overdueCount}</div>
      </div>
      <div class="tile week">
        <div class="label">Due this week</div>
        <div class="value">${dueThisWeek}</div>
      </div>
      <div class="tile completed">
        <div class="label">Completed this month</div>
        <div class="value">${completedThisMonth}</div>
      </div>
      <div class="tile upcoming">
        <div class="label">Upcoming (30 days)</div>
        <div class="value">${upcomingCount}</div>
      </div>`;
}

function renderTaskSection(containerId, tasks, taskType) {
    const container = document.getElementById(containerId);
    if (!container) return;

    // Hide the entire Overdue section when empty; otherwise show it
    if (!tasks || tasks.length === 0) {
        if (containerId === 'overdue-tasks') {
            const wrapper = container.closest('.task-section');
            if (wrapper) wrapper.style.display = 'none';
            return;
        }
        // For other sections, keep an empty state
        container.innerHTML = '<p>No tasks in this category.</p>';
        return;
    }

    // Ensure overdue section is visible when data exists again
    if (containerId === 'overdue-tasks') {
        const wrapper = container.closest('.task-section');
        if (wrapper) wrapper.style.display = '';
    }

    // Cache tasks for editing
    tasks.forEach(t => { tasksCache[t.id] = t; });

    const cards = tasks.map(task => {
        const statusClass = taskType; // overdue | upcoming | future | completed
        const useRelative = (taskType === 'upcoming' || taskType === 'overdue');
        const dueLabel = useRelative
            ? getRelativeDueLabel(task.next_due_date)
            : (task.next_due_date ? formatDate(task.next_due_date) : '');
        return buildTaskCard(task, { statusClass, dueLabel, isUrgent: false, taskType });
    }).join('');

    container.innerHTML = `<div class="task-card-list">${cards}</div>`;
}

// Edit modal functions
function openEditModal(taskId) {
    const task = tasksCache[taskId];
    if (!task) return;
    editingTaskId = taskId;
    document.getElementById('edit-title').value = task.title || '';
    document.getElementById('edit-description').value = task.description || '';
    document.getElementById('edit-frequency').value = task.frequency_days || '';
    document.getElementById('edit-priority').value = task.priority || '';
    document.getElementById('edit-category').value = task.category || '';
    const dueInput = document.getElementById('edit-due-date');
    if (dueInput) {
        if (task.next_due_date) {
            const d = new Date(task.next_due_date);
            const yyyy = d.getFullYear();
            const mm = String(d.getMonth() + 1).padStart(2, '0');
            const dd = String(d.getDate()).padStart(2, '0');
            dueInput.value = `${yyyy}-${mm}-${dd}`;
        } else {
            dueInput.value = '';
        }
    }
    clearEditValidation();
    const modal = document.getElementById('edit-modal');
    if (modal) modal.style.display = 'flex';
}

function closeEditModal() {
    const modal = document.getElementById('edit-modal');
    if (modal) modal.style.display = 'none';
    editingTaskId = null;
}

async function saveEditTask() {
    if (!editingTaskId) return;
    const title = document.getElementById('edit-title').value.trim();
    const description = document.getElementById('edit-description').value.trim();
    const frequency = parseInt(document.getElementById('edit-frequency').value, 10);
    const priority = document.getElementById('edit-priority').value || null;
    const category = document.getElementById('edit-category').value.trim() || null;
    const next_due_date = (document.getElementById('edit-due-date') && document.getElementById('edit-due-date').value) ? document.getElementById('edit-due-date').value : null;
    if (!validateEditForm()) return;
    try {
        const response = await fetch(`${API_BASE_URL}/api/tasks/${editingTaskId}`, {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${authToken}`
            },
            body: JSON.stringify({ title, description, frequency_days: frequency, priority, category, next_due_date })
        });
        const data = await response.json();
        if (response.ok) {
            showFlashMessage('Task updated');
            closeEditModal();
            loadDashboardData();
        } else {
            showFlashMessage(data.error || 'Failed to update task', 'error');
        }
    } catch (e) {
        showFlashMessage('Network error', 'error');
    }
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
        has_water_heater: document.getElementById('has_water_heater').checked,
        has_water_softener: document.getElementById('has_water_softener').checked,
        has_garbage_disposal: document.getElementById('has_garbage_disposal').checked,
        has_washer_dryer: document.getElementById('has_washer_dryer').checked,
        has_sump_pump: document.getElementById('has_sump_pump').checked,
        has_well: document.getElementById('has_well').checked,
        has_fireplace: document.getElementById('has_fireplace').checked,
        has_septic: document.getElementById('has_septic').checked,
        has_garage: document.getElementById('has_garage').checked
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
function showFlashMessage(message, type = 'success', { timeoutMs = 5000 } = {}) {
    const wrap = document.getElementById('flash-messages');
    if (!wrap) return;
    const el = document.createElement('div');
    el.className = `flash-message ${type}`;
    el.innerHTML = `
      <span class="flash-text"></span>
      <button class="flash-close" aria-label="Close" type="button">&times;</button>
    `;
    el.querySelector('.flash-text').textContent = message;
    wrap.appendChild(el);
    if (timeoutMs && timeoutMs > 0) {
        setTimeout(() => {
            if (el && el.parentNode) el.remove();
        }, timeoutMs);
    }
}

function formatDate(dateString) {
    const date = new Date(dateString);
    return date.toLocaleDateString();
}

// Returns Good morning/afternoon/evening
function getTimeOfDayGreeting() {
    const h = new Date().getHours();
    if (h < 12) return 'Good morning';
    if (h < 18) return 'Good afternoon';
    return 'Good evening';
}
