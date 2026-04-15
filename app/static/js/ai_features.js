const QuorumAI = (() => {
  const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content || '';
  const debounceMap = new Map();

  function showToast(message, level = 'danger') {
    const wrapper = document.createElement('div');
    wrapper.className = `alert alert-${level} position-fixed top-0 end-0 m-3`;
    wrapper.style.zIndex = 1090;
    wrapper.textContent = message;
    document.body.appendChild(wrapper);
    setTimeout(() => wrapper.remove(), 3500);
  }

  function escapeHtml(value) {
    return String(value || '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function sanitizeText(value, maxLength) {
    return String(value || '').replace(/\s+/g, ' ').trim().slice(0, maxLength);
  }

  function buildChallengeCreateUrl(baseUrl, challenge, domain, geography) {
    const challengeTitle = sanitizeText(challenge?.title, 500);
    const challengeDescription = sanitizeText(challenge?.description, 2200);
    const challengeRationale = sanitizeText(challenge?.rationale, 700);
    const descriptionWithContext = [
      challengeDescription,
      challengeRationale ? `Why this matters: ${challengeRationale}` : '',
    ].filter(Boolean).join('\n\n').slice(0, 3000);

    const params = new URLSearchParams();
    params.set('title', challengeTitle);
    params.set('description', descriptionWithContext);
    params.set('domain', sanitizeText(domain || 'community', 100) || 'community');
    params.set('geographic_scope', sanitizeText(geography || 'India', 200) || 'India');

    const timeline = Number(challenge?.suggested_timeline_days);
    if ([30, 60, 90].includes(timeline)) {
      params.set('suggested_timeline_days', String(timeline));
    }

    const difficulty = sanitizeText(challenge?.difficulty, 32).toLowerCase();
    if (difficulty) {
      params.set('difficulty', difficulty);
    }

    const teamSize = Number(challenge?.estimated_team_size);
    if (Number.isInteger(teamSize) && teamSize >= 3 && teamSize <= 12) {
      params.set('estimated_team_size', String(teamSize));
    }

    return `${baseUrl}?${params.toString()}`;
  }

  async function callAI(endpoint, payload, targetElement, onSuccess) {
    try {
      const res = await fetch(endpoint, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': csrfToken,
        },
        body: JSON.stringify(payload),
      });
      if (!res.ok) {
        throw new Error('AI request failed');
      }
      const data = await res.json();
      onSuccess(data, targetElement);
    } catch (_error) {
      showToast('AI assistant is temporarily unavailable. Please try again.');
    }
  }

  function debounce(key, fn, delay = 600) {
    clearTimeout(debounceMap.get(key));
    const timeoutId = setTimeout(fn, delay);
    debounceMap.set(key, timeoutId);
  }

  function attachHandlers() {
    document.querySelectorAll('.ai-trigger').forEach((btn) => {
      btn.addEventListener('click', () => {
        const endpoint = btn.dataset.aiEndpoint;
        const action = btn.dataset.aiAction;
        const targetSelector = btn.dataset.aiTarget;
        const targetEl = document.querySelector(targetSelector);
        btn.disabled = true;
        const originalText = btn.textContent;
        btn.textContent = 'Asking AI...';

        debounce(endpoint + action, () => {
          const payload = buildPayload(action, targetEl);
          callAI(endpoint, payload, targetEl, (data, element) => {
            renderAIResult(action, data, element, btn);
            btn.disabled = false;
            btn.textContent = originalText;
          });
        }, 50);
      });
    });
  }

  function buildPayload(action, targetEl) {
    if (action === 'enhance_description') {
      return {text: targetEl?.value || ''};
    }
    if (action === 'validate_scope') {
      return {
        success_definition: targetEl?.value || '',
        timeline_days: Number(document.querySelector('select[name="timeline_days"]')?.value || 60),
        project_type: document.querySelector('select[name="project_type"]')?.value || 'awareness',
      };
    }
    if (action === 'suggest_roles') {
      return {
        project_type: document.querySelector('input[name="project_type"]:checked')?.value || 'awareness',
        domain: document.querySelector('select[name="domain"]')?.value || 'community',
        problem_statement: document.querySelector('#problemStatementInput')?.value || '',
      };
    }
    if (action === 'outcome_assist') {
      return {};
    }
    if (action === 'recommend') {
      return {};
    }
    if (action === 'template_search') {
      return {query: targetEl?.value || ''};
    }
    if (action === 'org_challenges') {
      return {
        geography: document.querySelector('input[name="geographic_scope"]')?.value || 'India',
        domain: document.querySelector('input[name="domain"]')?.value || 'community',
      };
    }
    return {};
  }

  function renderAIResult(action, data, targetEl, triggerButton = null) {
    if (action === 'enhance_description') {
      const box = document.querySelector('#ai-result-enhance');
      box.classList.remove('d-none');
      box.innerHTML = `${data.enhanced_description || ''}<div class="mt-2"><button class="btn btn-sm btn-primary" id="useEnhanced">Use This</button> <button class="btn btn-sm btn-outline-secondary" id="dismissEnhanced">Dismiss</button></div>`;
      document.querySelector('#useEnhanced')?.addEventListener('click', () => {
        if (targetEl) targetEl.value = data.enhanced_description || '';
      });
      document.querySelector('#dismissEnhanced')?.addEventListener('click', () => box.classList.add('d-none'));
    }

    if (action === 'validate_scope') {
      const box = document.querySelector('#ai-result-scope');
      box.classList.remove('d-none');
      box.innerHTML = `<strong>${data.is_valid ? 'Looks feasible' : 'Scope warning'}</strong><p class="mb-1">${data.feedback || ''}</p>`;
    }

    if (action === 'suggest_roles') {
      const box = document.querySelector('#ai-result-roles');
      box.classList.remove('d-none');
      const rows = (data.suggested_roles || [])
        .map((role) => `<div class="border rounded p-2 mb-2"><strong>${role.title}</strong><div>${role.description}</div><button class="btn btn-sm btn-outline-primary mt-1 use-role" data-title="${role.title}" data-description="${role.description}" data-hours="${role.hours_per_week || 4}">Use This</button></div>`)
        .join('');
      box.innerHTML = rows || 'No suggestions found.';
      box.querySelectorAll('.use-role').forEach((btn) => {
        btn.addEventListener('click', () => {
          const container = document.querySelector('#rolesContainer');
          const roleBlock = document.createElement('div');
          roleBlock.className = 'role-block border rounded p-3 mb-3';
          roleBlock.innerHTML = `<div class="row g-2"><div class="col-md-4"><input class="form-control" name="role_title" value="${btn.dataset.title}" required></div><div class="col-md-4"><input class="form-control" name="role_skill_tags"></div><div class="col-md-2"><input class="form-control" name="role_hours" value="${btn.dataset.hours}"></div><div class="col-md-2"><select class="form-select" name="role_is_mvt_required"><option value="true">MVT</option><option value="false">Optional</option></select></div><div class="col-12"><textarea class="form-control" name="role_description">${btn.dataset.description}</textarea></div></div><button type="button" class="btn btn-sm btn-outline-danger mt-2 remove-role">Remove Role</button>`;
          container.appendChild(roleBlock);
        });
      });
    }

    if (action === 'outcome_assist') {
      const box = document.querySelector('#ai-result-outcome');
      box.classList.remove('d-none');
      box.innerHTML = `${data.outcome_draft || ''}<div class="mt-2"><button class="btn btn-sm btn-primary" id="useOutcomeDraft">Use This</button></div>`;
      document.querySelector('#useOutcomeDraft')?.addEventListener('click', () => {
        const field = document.querySelector('#outcome_achieved');
        if (field) field.value = data.outcome_draft || '';
      });
    }

    if (action === 'recommend') {
      const box = document.querySelector('#ai-result-recommend');
      box.classList.remove('d-none');
      box.textContent = data.explanation || '';
    }

    if (action === 'template_search') {
      const box = document.querySelector('#ai-result-template-search');
      box.classList.remove('d-none');
      const ids = data.matched_template_ids || [];
      box.textContent = `Matched template IDs: ${ids.join(', ')}`;
      document.querySelectorAll('.template-item').forEach((node) => {
        node.style.display = ids.length === 0 || ids.includes(Number(node.dataset.templateId)) ? '' : 'none';
      });
    }

    if (action === 'org_challenges') {
      const box = document.querySelector('#ai-result-org-challenges');
      box.classList.remove('d-none');

      const challengeCreateUrl = triggerButton?.dataset.aiCreateUrl || '/org/challenges/post';
      const selectedGeography = document.querySelector('input[name="geographic_scope"]')?.value || 'India';
      const selectedDomain = document.querySelector('input[name="domain"]')?.value || 'community';

      const content = (data.challenges || [])
        .map((challenge) => {
          const createUrl = buildChallengeCreateUrl(challengeCreateUrl, challenge, selectedDomain, selectedGeography);
          const difficulty = escapeHtml(challenge.difficulty || 'intermediate');
          const timeline = Number(challenge.suggested_timeline_days) || 60;
          const teamSize = Number(challenge.estimated_team_size) || 6;

          return `
            <div class="border rounded p-3 mb-2 bg-white">
              <strong>${escapeHtml(challenge.title)}</strong>
              <p class="small mb-1 mt-2">${escapeHtml(challenge.description)}</p>
              <div class="small text-muted mb-2">${escapeHtml(challenge.rationale)}</div>
              <div class="d-flex flex-wrap gap-2 mb-2">
                <span class="badge text-bg-light border">${difficulty}</span>
                <span class="badge text-bg-light border">${timeline} days</span>
                <span class="badge text-bg-light border">${teamSize} people</span>
              </div>
              <a class="btn btn-sm btn-primary" href="${escapeHtml(createUrl)}">Create Challenge</a>
            </div>
          `;
        })
        .join('');
      box.innerHTML = content || 'No challenge insights currently available.';
    }
  }

  return {attachHandlers, callAI};
})();

document.addEventListener('DOMContentLoaded', () => {
  QuorumAI.attachHandlers();
});
