(() => {
  const app = document.getElementById("analyticsApp");
  if (!app || typeof Chart === "undefined") {
    return;
  }

  const endpoint = app.dataset.endpoint || "";
  const defaultRange = app.dataset.defaultRange || "30d";
  const loadingEl = document.getElementById("analyticsLoading");
  const contentEl = document.getElementById("analyticsContent");
  const kpiRowEl = document.getElementById("kpiRow");

  const chartInstances = {};
  const sparklineInstances = [];
  const PLAN_PRICES = {
    creator_pro: 749,
    org_starter: 4999,
    org_team: 14999,
  };

  function getCssVar(name, fallback) {
    const value = getComputedStyle(document.documentElement).getPropertyValue(name);
    return (value || "").trim() || fallback;
  }

  const palette = {
    darkGreen: getCssVar("--quorum-dark-green", "#14532d"),
    midGreen: getCssVar("--quorum-mid-green", "#1f8a4c"),
    mint: getCssVar("--quorum-mint", "#d5f5e3"),
    orange: getCssVar("--quorum-orange", "#f97316"),
    slate: "#334155",
    blue: "#2563eb",
    yellow: "#ca8a04",
    rose: "#e11d48",
    indigo: "#4f46e5",
    teal: "#0d9488",
    amber: "#d97706",
    gray: "#6b7280",
  };

  const chartColors = [
    palette.midGreen,
    palette.orange,
    palette.blue,
    palette.indigo,
    palette.teal,
    palette.yellow,
    palette.rose,
    "#7c3aed",
    "#0f766e",
    "#be123c",
    "#ea580c",
    "#374151",
  ];

  function configureChartDefaults() {
    Chart.defaults.animation = {
      duration: 850,
      easing: "easeOutQuart",
    };
    Chart.defaults.color = "#334155";
    Chart.defaults.font.family = "Inter, system-ui, sans-serif";
    Chart.defaults.plugins.legend.labels.usePointStyle = true;
    Chart.defaults.plugins.legend.labels.boxWidth = 10;
    Chart.defaults.plugins.tooltip.backgroundColor = "#0f172a";
    Chart.defaults.plugins.tooltip.titleColor = "#ffffff";
    Chart.defaults.plugins.tooltip.bodyColor = "#ffffff";
    Chart.defaults.plugins.tooltip.padding = 10;
    Chart.defaults.plugins.tooltip.cornerRadius = 10;
    Chart.defaults.plugins.tooltip.displayColors = true;
  }

  const centerTextPlugin = {
    id: "centerTextPlugin",
    afterDraw(chart, _args, pluginOptions) {
      if (chart.config.type !== "doughnut") {
        return;
      }
      const centerLabel = pluginOptions && pluginOptions.text;
      if (!centerLabel) {
        return;
      }
      const { ctx, chartArea } = chart;
      if (!chartArea) {
        return;
      }
      const x = (chartArea.left + chartArea.right) / 2;
      const y = (chartArea.top + chartArea.bottom) / 2;

      ctx.save();
      ctx.fillStyle = "#0f172a";
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.font = "700 18px Inter, system-ui, sans-serif";
      ctx.fillText(String(centerLabel), x, y - 2);
      ctx.font = "500 11px Inter, system-ui, sans-serif";
      ctx.fillStyle = "#64748b";
      ctx.fillText("projects", x, y + 16);
      ctx.restore();
    },
  };

  function escapeHtml(value) {
    return String(value || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/\"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function formatNumber(value) {
    const num = Number(value || 0);
    return new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 }).format(num);
  }

  function formatCurrency(value) {
    const num = Number(value || 0);
    return `₹${new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 }).format(num)}`;
  }

  function formatDate(isoString) {
    if (!isoString) {
      return "-";
    }
    const parsed = new Date(isoString);
    if (Number.isNaN(parsed.getTime())) {
      return "-";
    }
    return parsed.toLocaleDateString("en-IN", {
      day: "2-digit",
      month: "short",
      year: "numeric",
    });
  }

  function formatDateTime(isoString) {
    if (!isoString) {
      return "-";
    }
    const parsed = new Date(isoString);
    if (Number.isNaN(parsed.getTime())) {
      return "-";
    }
    return parsed.toLocaleString("en-IN", {
      day: "2-digit",
      month: "short",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  }

  function setLoading(isLoading) {
    if (loadingEl) {
      loadingEl.classList.toggle("d-none", !isLoading);
    }
    if (contentEl) {
      contentEl.classList.toggle("d-none", isLoading);
    }
  }

  function setActiveRange(rangeKey) {
    document.querySelectorAll(".analytics-range-btn").forEach((button) => {
      button.classList.toggle("active", button.dataset.range === rangeKey);
    });
  }

  function showError(message) {
    const existing = document.getElementById("analyticsError");
    if (existing) {
      existing.remove();
    }
    const alert = document.createElement("div");
    alert.id = "analyticsError";
    alert.className = "alert alert-danger";
    alert.textContent = message || "Failed to load analytics.";
    app.prepend(alert);
  }

  function clearError() {
    const existing = document.getElementById("analyticsError");
    if (existing) {
      existing.remove();
    }
  }

  function destroyCharts() {
    Object.keys(chartInstances).forEach((key) => {
      if (chartInstances[key]) {
        chartInstances[key].destroy();
      }
      delete chartInstances[key];
    });

    while (sparklineInstances.length > 0) {
      const chart = sparklineInstances.pop();
      if (chart) {
        chart.destroy();
      }
    }
  }

  function createChart(canvasId, config) {
    const canvas = document.getElementById(canvasId);
    if (!canvas) {
      return null;
    }
    if (chartInstances[canvasId]) {
      chartInstances[canvasId].destroy();
    }
    const instance = new Chart(canvas.getContext("2d"), config);
    chartInstances[canvasId] = instance;
    return instance;
  }

  function statusToneClass(direction) {
    if (direction === "up") {
      return "up";
    }
    if (direction === "down") {
      return "down";
    }
    return "neutral";
  }

  function statusSymbol(direction) {
    if (direction === "up") {
      return "↑";
    }
    if (direction === "down") {
      return "↓";
    }
    return "-";
  }

  function renderKpiCards(kpis) {
    if (!kpiRowEl) {
      return;
    }

    while (sparklineInstances.length > 0) {
      const chart = sparklineInstances.pop();
      if (chart) {
        chart.destroy();
      }
    }

    kpiRowEl.innerHTML = (kpis || [])
      .map((kpi, index) => {
        const toneClass = statusToneClass(kpi?.change?.direction);
        const iconTone = kpi?.tone === "orange" ? "orange" : "";
        const changeValue = kpi?.change?.value;
        const changeText =
          changeValue === null || typeof changeValue === "undefined"
            ? "No previous baseline"
            : `${statusSymbol(kpi?.change?.direction)} ${Math.abs(Number(changeValue || 0)).toFixed(1)}%`;

        const metricValue = kpi?.id === "revenue_inr" ? formatCurrency(kpi?.value) : formatNumber(kpi?.value);

        return `
          <article class="analytics-kpi-card">
            <div class="analytics-kpi-header">
              <div class="small text-muted">${escapeHtml(kpi?.label)}</div>
              <span class="analytics-kpi-icon ${iconTone}"><i class="bi ${escapeHtml(kpi?.icon || "bi-graph-up")}"></i></span>
            </div>
            <div class="analytics-kpi-value">${metricValue}</div>
            <div class="analytics-kpi-change ${toneClass}">${changeText}</div>
            <canvas class="analytics-kpi-sparkline" id="sparkline-${index}" height="34"></canvas>
          </article>
        `;
      })
      .join("");

    (kpis || []).forEach((kpi, index) => {
      const canvas = document.getElementById(`sparkline-${index}`);
      if (!canvas) {
        return;
      }
      const chart = new Chart(canvas.getContext("2d"), {
        type: "line",
        data: {
          labels: (kpi.sparkline || []).map((_v, idx) => idx + 1),
          datasets: [
            {
              data: kpi.sparkline || [],
              borderColor: palette.midGreen,
              backgroundColor: "transparent",
              borderWidth: 2,
              pointRadius: 0,
              tension: 0.35,
            },
          ],
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: {
            legend: { display: false },
            tooltip: { enabled: false },
          },
          scales: {
            x: { display: false },
            y: { display: false },
          },
        },
      });
      sparklineInstances.push(chart);
    });
  }

  function renderUserGrowth(chartData) {
    const canvas = document.getElementById("chartUserGrowth");
    if (!canvas) {
      return;
    }
    const ctx = canvas.getContext("2d");
    const gradient = ctx.createLinearGradient(0, 0, 0, 320);
    gradient.addColorStop(0, "rgba(16, 185, 129, 0.32)");
    gradient.addColorStop(1, "rgba(16, 185, 129, 0.02)");

    createChart("chartUserGrowth", {
      type: "line",
      data: {
        labels: chartData.labels || [],
        datasets: [
          {
            label: "Total Users",
            data: chartData.total_users || [],
            borderColor: palette.midGreen,
            backgroundColor: gradient,
            fill: true,
            tension: 0.35,
            pointRadius: 0,
          },
          {
            label: "New Signups",
            data: chartData.new_signups || [],
            borderColor: palette.orange,
            backgroundColor: "transparent",
            fill: false,
            tension: 0.3,
            pointRadius: 0,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: true },
        },
      },
    });
  }

  function renderProjectActivity(chartData) {
    createChart("chartProjectActivity", {
      type: "line",
      data: {
        labels: chartData.labels || [],
        datasets: [
          {
            label: "Projects Created",
            data: chartData.created || [],
            borderColor: palette.blue,
            tension: 0.35,
            pointRadius: 0,
          },
          {
            label: "Projects Launched",
            data: chartData.launched || [],
            borderColor: palette.midGreen,
            tension: 0.35,
            pointRadius: 0,
          },
          {
            label: "Projects Completed",
            data: chartData.completed || [],
            borderColor: palette.orange,
            tension: 0.35,
            pointRadius: 0,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
      },
    });
  }

  function renderProjectStatus(chartData) {
    const statusTotal = document.getElementById("projectStatusTotal");
    if (statusTotal) {
      statusTotal.textContent = formatNumber(chartData.total || 0);
    }

    createChart("chartProjectStatus", {
      type: "doughnut",
      data: {
        labels: chartData.labels || [],
        datasets: [
          {
            data: chartData.values || [],
            backgroundColor: [
              "#94a3b8",
              palette.teal,
              "#0ea5e9",
              palette.midGreen,
              palette.orange,
              "#6b7280",
            ],
            borderWidth: 0,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          centerTextPlugin: {
            text: formatNumber(chartData.total || 0),
          },
        },
        onClick(_event, activeElements) {
          if (!activeElements || !activeElements.length) {
            return;
          }
          const index = activeElements[0].index;
          const link = (chartData.links || [])[index];
          if (link) {
            window.location.href = link;
          }
        },
      },
    });
  }

  function renderDomainDistribution(chartData) {
    createChart("chartDomainDistribution", {
      type: "bar",
      data: {
        labels: chartData.labels || [],
        datasets: [
          {
            label: "Projects",
            data: chartData.values || [],
            backgroundColor: chartColors,
            borderRadius: 8,
          },
        ],
      },
      options: {
        indexAxis: "y",
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          tooltip: {
            callbacks: {
              label(context) {
                const idx = context.dataIndex;
                const value = Number(context.raw || 0);
                const pct = Number((chartData.percentages || [])[idx] || 0).toFixed(2);
                return `${formatNumber(value)} projects (${pct}%)`;
              },
            },
          },
        },
      },
    });
  }

  function renderGeoDistribution(chartData) {
    createChart("chartGeoDistribution", {
      type: "bar",
      data: {
        labels: chartData.labels || [],
        datasets: [
          {
            label: "Projects",
            data: chartData.values || [],
            backgroundColor: palette.midGreen,
            borderRadius: 8,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
      },
    });

    const tbody = document.getElementById("geoTableBody");
    if (!tbody) {
      return;
    }
    tbody.innerHTML = (chartData.table || [])
      .map(
        (row) => `
        <tr>
          <td>${formatNumber(row.rank)}</td>
          <td>${escapeHtml(row.country || "-")}</td>
          <td>${escapeHtml(row.city || "-")}</td>
          <td class="text-end">${formatNumber(row.projects)}</td>
          <td class="text-end">${formatNumber(row.contributors)}</td>
          <td class="text-end">${formatNumber(row.completed_projects)}</td>
        </tr>
      `
      )
      .join("");
  }

  function renderSkillDistribution(chartData) {
    createChart("chartSkillDistribution", {
      type: "radar",
      data: {
        labels: chartData.labels || [],
        datasets: [
          {
            label: "Users",
            data: chartData.values || [],
            backgroundColor: "rgba(16, 185, 129, 0.25)",
            borderColor: palette.midGreen,
            borderWidth: 2,
            pointRadius: 3,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        scales: {
          r: {
            beginAtZero: true,
          },
        },
      },
    });
  }

  function renderApplicationFunnel(chartData) {
    const conversionEl = document.getElementById("applicationConversionRate");
    if (conversionEl) {
      conversionEl.textContent = `${Number(chartData.conversion_rate || 0).toFixed(2)}%`;
    }

    createChart("chartApplicationFunnel", {
      type: "bar",
      data: {
        labels: chartData.labels || [],
        datasets: [
          {
            label: "Applications",
            data: chartData.values || [],
            backgroundColor: [palette.blue, palette.yellow, palette.midGreen, palette.rose],
            borderRadius: 8,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
      },
    });
  }

  function renderTaskCompletion(chartData) {
    const canvas = document.getElementById("chartTaskCompletion");
    if (!canvas) {
      return;
    }
    const ctx = canvas.getContext("2d");
    const gradient = ctx.createLinearGradient(0, 0, 0, 300);
    gradient.addColorStop(0, "rgba(34, 197, 94, 0.35)");
    gradient.addColorStop(1, "rgba(34, 197, 94, 0.03)");

    createChart("chartTaskCompletion", {
      type: "line",
      data: {
        labels: chartData.labels || [],
        datasets: [
          {
            label: "Task Completion %",
            data: chartData.completion_rate || [],
            borderColor: palette.midGreen,
            backgroundColor: gradient,
            yAxisID: "y",
            fill: true,
            tension: 0.35,
            pointRadius: 0,
          },
          {
            label: "Active Projects",
            data: chartData.active_projects || [],
            borderColor: palette.blue,
            yAxisID: "y1",
            fill: false,
            tension: 0.3,
            pointRadius: 0,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        scales: {
          y: {
            min: 0,
            max: 100,
            ticks: {
              callback(value) {
                return `${value}%`;
              },
            },
          },
          y1: {
            position: "right",
            grid: {
              drawOnChartArea: false,
            },
            beginAtZero: true,
          },
        },
      },
    });
  }

  function renderRevenue(chartData) {
    createChart("chartRevenue", {
      type: "bar",
      data: {
        labels: chartData.labels || [],
        datasets: [
          {
            label: "Creator Pro",
            data: chartData.creator_pro || [],
            backgroundColor: palette.midGreen,
            stack: "revenue",
          },
          {
            label: "Org Starter",
            data: chartData.org_starter || [],
            backgroundColor: palette.orange,
            stack: "revenue",
          },
          {
            label: "Org Team",
            data: chartData.org_team || [],
            backgroundColor: palette.indigo,
            stack: "revenue",
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        scales: {
          x: {
            stacked: true,
          },
          y: {
            stacked: true,
            ticks: {
              callback(value) {
                return formatCurrency(value);
              },
            },
          },
        },
      },
    });

    const summary = chartData.summary || {};
    const revenueSummaryBody = document.getElementById("revenueSummaryBody");
    if (!revenueSummaryBody) {
      return;
    }

    const creatorCount = Number(summary.creator_pro_subscribers || 0);
    const starterCount = Number(summary.org_starter_subscribers || 0);
    const teamCount = Number(summary.org_team_subscribers || 0);

    const rows = [
      {
        plan: "Creator Pro",
        subscribers: creatorCount,
        mrr: creatorCount * PLAN_PRICES.creator_pro,
      },
      {
        plan: "Org Starter",
        subscribers: starterCount,
        mrr: starterCount * PLAN_PRICES.org_starter,
      },
      {
        plan: "Org Team",
        subscribers: teamCount,
        mrr: teamCount * PLAN_PRICES.org_team,
      },
    ];

    revenueSummaryBody.innerHTML = [
      ...rows.map(
        (row) => `
        <tr>
          <td>${row.plan}</td>
          <td class="text-end">${formatNumber(row.subscribers)}</td>
          <td class="text-end">${formatCurrency(row.mrr)}</td>
        </tr>
      `
      ),
      `
      <tr class="fw-semibold border-top">
        <td>Total MRR</td>
        <td class="text-end">${formatNumber(creatorCount + starterCount + teamCount)}</td>
        <td class="text-end">${formatCurrency(summary.total_mrr_inr || 0)}</td>
      </tr>
      `,
    ].join("");
  }

  function renderAiUsage(chartData) {
    createChart("chartAiUsage", {
      type: "pie",
      data: {
        labels: chartData.labels || [],
        datasets: [
          {
            data: chartData.values || [],
            backgroundColor: chartColors,
            borderWidth: 0,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
      },
    });
  }

  function renderBlogPerformance(chartData) {
    createChart("chartBlogPerformance", {
      type: "bar",
      data: {
        labels: chartData.labels || [],
        datasets: [
          {
            label: "Views",
            data: chartData.views || [],
            backgroundColor: palette.midGreen,
            yAxisID: "y",
            borderRadius: 6,
          },
          {
            label: "Reading Time (min)",
            data: chartData.reading_time || [],
            backgroundColor: palette.orange,
            yAxisID: "y1",
            borderRadius: 6,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        scales: {
          y: {
            beginAtZero: true,
            position: "left",
          },
          y1: {
            beginAtZero: true,
            position: "right",
            grid: {
              drawOnChartArea: false,
            },
          },
        },
      },
    });

    const tbody = document.getElementById("blogTableBody");
    if (!tbody) {
      return;
    }
    tbody.innerHTML = (chartData.table || [])
      .map(
        (row) => `
        <tr>
          <td><a href="/blog/${encodeURIComponent(row.slug || "")}" target="_blank" rel="noopener">${escapeHtml(row.title)}</a></td>
          <td>${escapeHtml(row.category || "-")}</td>
          <td class="text-end">${formatNumber(row.views)}</td>
          <td>${formatDate(row.published_date)}</td>
          <td class="text-end">${formatNumber(row.reading_time)} min</td>
          <td>${row.featured ? "Yes" : "No"}</td>
        </tr>
      `
      )
      .join("");
  }

  function renderDigestEngagement(chartData) {
    const datasets = [
      {
        label: "Emails Sent",
        data: chartData.sent || [],
        borderColor: palette.midGreen,
        backgroundColor: "transparent",
        tension: 0.35,
        pointRadius: 0,
      },
    ];

    if (chartData.has_open_data) {
      datasets.push({
        label: "Opens",
        data: chartData.opens || [],
        borderColor: palette.orange,
        backgroundColor: "transparent",
        tension: 0.35,
        pointRadius: 0,
      });
    }

    createChart("chartDigestEngagement", {
      type: "line",
      data: {
        labels: chartData.labels || [],
        datasets,
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
      },
    });
  }

  function statusBadge(status) {
    const normalized = String(status || "").toLowerCase();
    if (normalized === "active") {
      return '<span class="badge text-bg-success">Active</span>';
    }
    if (normalized === "assembling") {
      return '<span class="badge text-bg-warning">Assembling</span>';
    }
    if (normalized === "completed") {
      return '<span class="badge text-bg-primary">Completed</span>';
    }
    if (normalized === "launch_ready") {
      return '<span class="badge text-bg-info">Launch Ready</span>';
    }
    if (normalized === "archived") {
      return '<span class="badge text-bg-secondary">Archived</span>';
    }
    return `<span class="badge text-bg-light border text-dark">${escapeHtml(normalized || "draft")}</span>`;
  }

  function renderContributors(rows) {
    const tbody = document.getElementById("contributorsTableBody");
    if (!tbody) {
      return;
    }

    tbody.innerHTML = (rows || [])
      .map((row) => {
        const avatar = row.avatar_url
          ? `<img src="${escapeHtml(row.avatar_url)}" alt="${escapeHtml(row.name)}" class="rounded-circle" width="28" height="28" style="object-fit: cover;">`
          : '<span class="rounded-circle bg-light border d-inline-flex align-items-center justify-content-center" style="width: 28px; height: 28px;"><i class="bi bi-person small"></i></span>';

        return `
          <tr>
            <td>${formatNumber(row.rank)}</td>
            <td>
              <div class="d-flex align-items-center gap-2">
                ${avatar}
                <a href="${escapeHtml(row.profile_link || `/profile/${encodeURIComponent(row.username || "")}`)}" target="_blank" rel="noopener">${escapeHtml(row.name)}</a>
              </div>
            </td>
            <td class="text-end">${formatNumber(row.projects_completed)}</td>
            <td class="text-end">${Number(row.peer_rating_average || 0).toFixed(2)}</td>
            <td class="text-end">${formatNumber(row.skills_count)}</td>
            <td>${formatDate(row.account_created)}</td>
            <td>${formatDate(row.last_login)}</td>
          </tr>
        `;
      })
      .join("");
  }

  function renderProjects(rows) {
    const tbody = document.getElementById("projectsTableBody");
    if (!tbody) {
      return;
    }

    tbody.innerHTML = (rows || [])
      .map((row) => {
        const progress = Math.max(0, Math.min(100, Number(row.milestone_progress || 0)));
        return `
          <tr>
            <td><a href="${escapeHtml(row.project_link || `/projects/${row.project_id}`)}" target="_blank" rel="noopener">${escapeHtml(row.title)}</a></td>
            <td><span class="badge text-bg-light border">${escapeHtml(String(row.domain || "").replace(/_/g, " "))}</span></td>
            <td>${statusBadge(row.status)}</td>
            <td>${escapeHtml(row.creator_name)}</td>
            <td class="text-end">${formatNumber(row.team_size)}</td>
            <td class="text-end">${formatNumber(row.tasks_completed)} / ${formatNumber(row.tasks_total)}</td>
            <td>
              <div class="progress" style="height: 8px; min-width: 84px;">
                <div class="progress-bar" style="width: ${progress}%; background-color: ${palette.midGreen};"></div>
              </div>
            </td>
            <td>${formatDate(row.started_date)}</td>
          </tr>
        `;
      })
      .join("");
  }

  function renderEvents(rows) {
    const feed = document.getElementById("eventsFeed");
    if (!feed) {
      return;
    }

    feed.innerHTML = (rows || [])
      .map(
        (event) => `
        <div class="analytics-event-item">
          <span class="analytics-event-icon"><i class="bi ${escapeHtml(event.icon || "bi-bell")}"></i></span>
          <div class="flex-grow-1">
            <div class="small mb-1">
              ${event.link ? `<a href="${escapeHtml(event.link)}" class="text-decoration-none">${escapeHtml(event.description)}</a>` : escapeHtml(event.description)}
            </div>
            <div class="small text-muted">
              ${escapeHtml(event.user || "")}
              ${event.user ? " · " : ""}
              ${formatDateTime(event.timestamp)}
            </div>
          </div>
        </div>
      `
      )
      .join("");
  }

  function renderCharts(payload) {
    const charts = payload.charts || {};

    renderUserGrowth(charts.user_growth || {});
    renderProjectActivity(charts.project_activity || {});
    renderProjectStatus(charts.project_status_distribution || {});
    renderDomainDistribution(charts.domain_distribution || {});
    renderGeoDistribution(charts.geographic_distribution || {});
    renderSkillDistribution(charts.skill_category_distribution || {});
    renderApplicationFunnel(charts.application_funnel || {});
    renderTaskCompletion(charts.task_completion_rate || {});
    renderRevenue(charts.revenue_breakdown || {});
    renderAiUsage(charts.ai_usage_distribution || {});
    renderBlogPerformance(charts.blog_performance || {});
    renderDigestEngagement(charts.weekly_digest_engagement || {});
  }

  function renderTables(payload) {
    const tables = payload.tables || {};
    renderContributors(tables.top_contributors || []);
    renderProjects(tables.most_active_projects || []);
    renderEvents(tables.recent_events || []);
  }

  function bindChartDownloads() {
    document.querySelectorAll(".js-chart-download").forEach((button) => {
      if (button.dataset.bound === "1") {
        return;
      }
      button.dataset.bound = "1";
      button.addEventListener("click", () => {
        const chartId = button.dataset.chartId;
        const chart = chartInstances[chartId];
        if (!chart) {
          return;
        }
        const link = document.createElement("a");
        link.href = chart.toBase64Image("image/png", 1);
        link.download = `${chartId}.png`;
        document.body.appendChild(link);
        link.click();
        link.remove();
      });
    });
  }

  async function loadAnalytics(rangeKey) {
    setActiveRange(rangeKey);
    setLoading(true);
    clearError();

    try {
      const url = `${endpoint}?range=${encodeURIComponent(rangeKey)}`;
      const response = await fetch(url, {
        method: "GET",
        headers: {
          Accept: "application/json",
          "X-Requested-With": "XMLHttpRequest",
        },
        credentials: "same-origin",
      });

      if (!response.ok) {
        throw new Error("Analytics request failed.");
      }

      const payload = await response.json();
      if (!payload.success) {
        throw new Error(payload.error || "Failed to load analytics data.");
      }

      destroyCharts();
      renderKpiCards(payload.kpis || []);
      renderCharts(payload);
      renderTables(payload);
      bindChartDownloads();
    } catch (error) {
      showError(error.message || "Failed to load analytics data.");
    } finally {
      setLoading(false);
    }
  }

  function bindControls() {
    document.querySelectorAll(".analytics-range-btn").forEach((button) => {
      button.addEventListener("click", () => {
        const rangeKey = button.dataset.range || "30d";
        loadAnalytics(rangeKey);
      });
    });

    const printButton = document.getElementById("printAnalyticsButton");
    if (printButton) {
      printButton.addEventListener("click", () => {
        window.print();
      });
    }
  }

  function init() {
    configureChartDefaults();
    try {
      Chart.register(centerTextPlugin);
    } catch (_error) {
      // Chart plugin may already be registered.
    }

    bindControls();
    bindChartDownloads();
    loadAnalytics(defaultRange);
  }

  init();
})();
