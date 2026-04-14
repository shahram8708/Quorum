(() => {
  const board = document.querySelector('#taskBoard');
  if (!board) return;

  const projectId = board.dataset.projectId;
  const createForm = document.querySelector('#taskCreateForm');
  const todoList = document.querySelector('#todoList');
  const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content || '';

  let dragged = null;

  function ensureFlashContainer() {
    let container = document.querySelector('.flash-container');
    if (!container) {
      container = document.createElement('div');
      container.className = 'flash-container';
      document.body.appendChild(container);
    }
    return container;
  }

  function showFlash(message, level = 'warning') {
    const normalizedLevel = level === 'error' ? 'danger' : level;
    const container = ensureFlashContainer();

    const alert = document.createElement('div');
    alert.className = `alert alert-${normalizedLevel} alert-dismissible fade show shadow`;
    alert.setAttribute('role', 'alert');
    alert.append(document.createTextNode(message));

    const closeButton = document.createElement('button');
    closeButton.type = 'button';
    closeButton.className = 'btn-close';
    closeButton.setAttribute('data-bs-dismiss', 'alert');
    closeButton.setAttribute('aria-label', 'Close');
    alert.appendChild(closeButton);

    container.appendChild(alert);
    setTimeout(() => {
      const alertInstance = bootstrap.Alert.getOrCreateInstance(alert);
      alertInstance.close();
    }, 6000);
  }

  function refreshCounts() {
    ['todo', 'in_progress', 'done'].forEach((status) => {
      const countNode = document.querySelector(`[data-count="${status}"]`);
      const list = document.querySelector(`.kanban-column[data-status="${status}"] .task-list`);
      if (countNode && list) countNode.textContent = list.querySelectorAll('.task-card').length;
    });
  }

  async function updateStatus(taskId, newStatus, version) {
    const endpoint = `/my-projects/${projectId}/tasks/${taskId}/status`;
    const res = await fetch(endpoint, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': csrfToken,
      },
      body: JSON.stringify({new_status: newStatus, version}),
    });

    if (res.status === 409) {
      showFlash('Conflict - reloading task', 'warning');
      return {conflict: true};
    }

    if (!res.ok) {
      showFlash('Task update failed', 'danger');
      return {error: true};
    }

    return res.json();
  }

  function attachDrag(card) {
    card.addEventListener('dragstart', () => {
      dragged = card;
      card.classList.add('dragging');
    });
    card.addEventListener('dragend', () => {
      dragged = null;
      card.classList.remove('dragging');
    });

    card.addEventListener('click', () => {
      const title = card.querySelector('strong')?.textContent || 'Task';
      const description = card.querySelector('p')?.textContent || '';
      showFlash(`${title}: ${description}`, 'info');
    });
  }

  document.querySelectorAll('.task-card').forEach(attachDrag);

  if (createForm) {
    createForm.addEventListener('submit', async (event) => {
      event.preventDefault();

      const submitButton = createForm.querySelector('button[type="submit"], button:not([type]), input[type="submit"]');
      if (submitButton) submitButton.disabled = true;

      try {
        const response = await fetch(createForm.action, {
          method: 'POST',
          headers: {
            'X-Requested-With': 'XMLHttpRequest',
            'X-CSRFToken': csrfToken,
            Accept: 'application/json',
          },
          body: new FormData(createForm),
        });

        const payload = await response.json();
        if (!response.ok || !payload.success) {
          showFlash(payload.message || 'Could not create task', 'danger');
          return;
        }

        if (payload.task_html && todoList) {
          todoList.insertAdjacentHTML('afterbegin', payload.task_html);
          const createdCard = todoList.firstElementChild;
          if (createdCard) attachDrag(createdCard);
          refreshCounts();
        }

        createForm.reset();
        const assigneeSelect = createForm.querySelector('[name="assigned_to_user_id"]');
        if (assigneeSelect) assigneeSelect.selectedIndex = 0;

        showFlash(payload.message || 'Task created successfully.', 'success');
      } catch {
        showFlash('Could not create task. Please try again.', 'danger');
      } finally {
        if (submitButton) submitButton.disabled = false;
      }
    });
  }

  document.querySelectorAll('.task-list').forEach((list) => {
    list.addEventListener('dragover', (event) => {
      event.preventDefault();
    });

    list.addEventListener('drop', async (event) => {
      event.preventDefault();
      if (!dragged) return;

      const card = dragged;
      const taskId = Number(card.dataset.taskId);
      const version = Number(card.dataset.version);
      const newStatus = list.closest('.kanban-column').dataset.status;

      const result = await updateStatus(taskId, newStatus, version);
      if (result?.success) {
        list.appendChild(card);
        card.dataset.version = result.new_version;
        if (newStatus === 'done') {
          card.classList.add('confetti');
          setTimeout(() => card.classList.remove('confetti'), 400);
        }
        refreshCounts();
      } else if (result?.conflict) {
        window.location.reload();
      }
    });
  });
})();
