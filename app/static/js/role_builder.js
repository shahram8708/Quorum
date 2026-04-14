(() => {
  const rolesContainer = document.querySelector('#rolesContainer');
  const addRoleBtn = document.querySelector('#addRoleBtn');
  if (!rolesContainer || !addRoleBtn) return;

  function roleCount() {
    return rolesContainer.querySelectorAll('.role-block').length;
  }

  rolesContainer.addEventListener('click', (event) => {
    const removeButton = event.target.closest('.remove-role');
    if (!removeButton) return;

    if (roleCount() <= 2) {
      alert('At least two roles are required.');
      return;
    }

    removeButton.closest('.role-block')?.remove();
  });

  addRoleBtn.addEventListener('click', () => {
    if (roleCount() >= 8) {
      alert('Maximum 8 roles allowed.');
      return;
    }
    const block = document.createElement('div');
    block.className = 'role-block border rounded p-3 mb-3';
    block.innerHTML = `
      <div class="row g-2">
        <div class="col-md-4"><input class="form-control" name="role_title" placeholder="Role title" required></div>
        <div class="col-md-4"><input class="form-control" name="role_skill_tags" placeholder="Skill IDs comma separated"></div>
        <div class="col-md-2"><input class="form-control" type="number" step="0.5" name="role_hours" value="4"></div>
        <div class="col-md-2"><select class="form-select" name="role_is_mvt_required"><option value="true">MVT</option><option value="false">Optional</option></select></div>
        <div class="col-12"><textarea class="form-control" name="role_description" rows="2" placeholder="Role description"></textarea></div>
      </div>
      <button type="button" class="btn btn-sm btn-outline-danger mt-2 remove-role">Remove Role</button>
    `;
    rolesContainer.appendChild(block);
  });
})();
