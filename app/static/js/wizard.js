(() => {
  const stepForm = document.querySelector('.wizard-page form');
  if (!stepForm) return;

  const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content || '';
  let unsavedChanges = false;

  stepForm.addEventListener('input', () => {
    unsavedChanges = true;
  });

  function validateRequiredFields() {
    let isValid = true;
    stepForm.querySelectorAll('[required]').forEach((field) => {
      field.classList.remove('is-invalid');
      if (!String(field.value || '').trim()) {
        field.classList.add('is-invalid');
        isValid = false;
      }
    });
    return isValid;
  }

  stepForm.addEventListener('submit', (event) => {
    if (!validateRequiredFields()) {
      event.preventDefault();
    }
  });

  function collectRoleDraft() {
    const rolesContainer = document.querySelector('#rolesContainer');
    if (!rolesContainer) return null;

    const roleBlocks = Array.from(rolesContainer.querySelectorAll('.role-block')).slice(0, 8);
    return roleBlocks.map((block) => ({
      title: block.querySelector('input[name="role_title"]')?.value || '',
      skill_tags: block.querySelector('input[name="role_skill_tags"]')?.value || '',
      hours_per_week: block.querySelector('input[name="role_hours"]')?.value || '',
      is_mvt_required: block.querySelector('select[name="role_is_mvt_required"]')?.value || 'true',
      description: block.querySelector('textarea[name="role_description"]')?.value || '',
    }));
  }

  async function autoSave() {
    const problemField = document.querySelector('#problemStatementInput');
    const successField = document.querySelector('#successDefinitionInput');
    const roleDraft = collectRoleDraft();
    const minTeamField = document.querySelector('input[name="min_viable_team_size"]');

    if (!problemField && !successField && !roleDraft) return;

    const payload = {};

    if (problemField) {
      payload.problem_statement = problemField.value || '';
    }

    if (successField) {
      payload.success_definition = successField.value || '';
    }

    if (roleDraft) {
      payload.roles = roleDraft;
      payload.min_viable_team_size = minTeamField?.value || '';
    }

    try {
      await fetch('/projects/new/auto-save', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': csrfToken,
        },
        body: JSON.stringify(payload),
      });
      unsavedChanges = false;
      showDraftStatus('Draft saved just now');
    } catch (_error) {
      showDraftStatus('Draft save failed');
    }
  }

  function showDraftStatus(text) {
    let status = document.querySelector('.draft-status');
    if (!status) {
      status = document.createElement('div');
      status.className = 'draft-status mt-2';
      stepForm.appendChild(status);
    }
    status.textContent = text;
  }

  setInterval(autoSave, 30000);

  window.addEventListener('beforeunload', (event) => {
    if (unsavedChanges) {
      event.preventDefault();
      event.returnValue = '';
    }
  });
})();
