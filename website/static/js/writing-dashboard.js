(function () {
  "use strict";

  const cache = new Map();

  function fetchJson(url) {
    if (!cache.has(url)) {
      cache.set(url, fetch(url, { credentials: "same-origin" }).then((response) => {
        if (!response.ok) throw new Error(`Could not load ${url}`);
        return response.json();
      }));
    }
    return cache.get(url);
  }

  function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>"']/g, (char) => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;"
    }[char]));
  }

  function toBool(value) {
    return String(value).toLowerCase() === "true";
  }

  function formatNumber(value) {
    return new Intl.NumberFormat().format(Number(value || 0));
  }

  function formatSigned(value) {
    const number = Number(value || 0);
    return `${number > 0 ? "+" : ""}${formatNumber(number)}`;
  }

  function renderShell(title, meta, body) {
    return `
      <div class="writing-dashboard__header">
        <h3 class="writing-dashboard__title">${escapeHtml(title)}</h3>
        ${meta ? `<span class="writing-dashboard__meta">${escapeHtml(meta)}</span>` : ""}
      </div>
      ${body}
    `;
  }

  function renderMetric(value, label, icon = "", modifier = "") {
    return `
      <div class="writing-metric ${modifier ? `writing-metric--${escapeHtml(modifier)}` : ""}">
        ${icon ? `<span class="writing-metric__icon" aria-hidden="true">${icon}</span>` : ""}
        <span class="writing-metric__text">
          <span class="writing-metric__value">${escapeHtml(value)}</span>
          <span class="writing-metric__label">${escapeHtml(label)}</span>
        </span>
      </div>
    `;
  }

  function renderActivity(element, data) {
    const activity = data.activity || {};
    const icons = activityIcons(element);
    element.innerHTML = `
      <div class="writing-metrics">
        ${renderMetric(formatNumber(activity.current_streak_days), "Current streak", icons.current)}
        ${renderMetric(formatNumber(activity.longest_streak_days), "Longest streak", icons.longest)}
        ${renderMetric(formatNumber(activity.active_days_total), "Active days", icons.active)}
        ${renderMetric(activity.latest_writing_day || "No data", "Latest writing day", icons.latest, "date")}
      </div>
      ${renderExternalGraphs(element)}
    `;
  }

  function activityIcons(element) {
    const template = element.querySelector("[data-writing-activity-icons]");
    const content = template?.content;
    const iconFor = (name) => content?.querySelector(`[data-activity-icon="${name}"]`)?.innerHTML || "";
    return {
      current: iconFor("current"),
      longest: iconFor("longest"),
      active: iconFor("active"),
      latest: iconFor("latest")
    };
  }

  function renderExternalGraphs(element) {
    const user = element.dataset.githubUser;
    if (!toBool(element.dataset.showExternal) || !user) return "";
    const encoded = encodeURIComponent(user);
    return `
      <div class="writing-external-graphs" aria-label="External GitHub activity images">
        <img loading="lazy" alt="GitHub streak stats for ${escapeHtml(user)}" src="https://streak-stats.demolab.com?user=${encoded}">
        <img loading="lazy" alt="GitHub activity graph for ${escapeHtml(user)}" src="https://github-readme-activity-graph.vercel.app/graph?username=${encoded}&theme=minimal">
      </div>
    `;
  }

  function renderCorpus(element, data) {
    const corpus = data.corpus || {};
    const body = `
      <div class="writing-metrics">
        ${renderMetric(formatNumber(corpus.draft_words), "Draft words")}
        ${renderMetric(formatNumber(corpus.published_words), "Published words")}
        ${renderMetric(formatNumber(corpus.total_tracked_words), "Total tracked words")}
      </div>
    `;
    element.innerHTML = renderShell("Tracked Corpus", generatedMeta(data), body);
  }

  function renderWordDelta(element, data) {
    const requestedDays = Math.max(1, Number.parseInt(element.dataset.days || "30", 10));
    const visibleDays = responsiveDays(element, requestedDays);
    const byDate = new Map((data.daily || []).map((day) => [day.date, day]));
    const daily = dateRange(visibleDays).map((date) => {
      const existing = byDate.get(date);
      return existing || { date, words_added: 0, words_removed: 0, net_words: 0 };
    });
    const graphDaily = dateRange(30).map((date) => {
      const existing = byDate.get(date);
      return existing || { date, words_added: 0, words_removed: 0, net_words: 0 };
    });
    if (!daily.length) {
      element.innerHTML = renderShell("Writing Changes", "", '<p class="writing-dashboard__empty">No daily word changes available yet.</p>');
      return;
    }
    const max = Math.max(1, ...daily.map((day) => Math.abs(day.words_added || 0) + Math.abs(day.words_removed || 0)));
    const firstDayOffset = daily.length ? new Date(`${daily[0].date}T00:00:00`).getDay() : 0;
    const leadingCells = Array.from({ length: firstDayOffset }, () => '<span class="word-delta__cell word-delta__cell--empty" aria-hidden="true"></span>').join("");
    const heatmapColumns = Math.ceil((firstDayOffset + daily.length) / 7);
    const monthLabels = renderHeatmapMonthLabels(daily, firstDayOffset, heatmapColumns);
    const cells = daily.map((day) => {
      const added = Number(day.words_added || 0);
      const removed = Number(day.words_removed || 0);
      const volume = Math.abs(added) + Math.abs(removed);
      const level = volume === 0 ? 0 : Math.max(1, Math.ceil(volume / max * 4));
      const direction = day.net_words < 0 ? "negative" : day.net_words > 0 ? "positive" : volume ? "mixed" : "none";
      const label = `${day.date}: ${formatNumber(added)} added, ${formatNumber(removed)} removed, ${formatSigned(day.net_words)} net`;
      return `
        <span class="word-delta__cell word-delta__cell--${direction} word-delta__cell--${level}" data-tooltip="${escapeHtml(label)}" aria-label="${escapeHtml(label)}" tabindex="0"></span>
      `;
    }).join("");
    const lineGraph = renderWordDeltaLineGraph(graphDaily);
    const totals = daily.reduce((sum, day) => {
      sum.added += Number(day.words_added || 0);
      sum.removed += Number(day.words_removed || 0);
      sum.net += Number(day.net_words || 0);
      return sum;
    }, { added: 0, removed: 0, net: 0 });
    element.innerHTML = renderShell("Writing Changes", `Last ${daily.length} days`, `
      <div class="word-delta__subtitle">Daily change intensity</div>
      <div class="word-delta__month-labels" style="--heatmap-columns:${heatmapColumns}" aria-hidden="true">${monthLabels}</div>
      <div class="word-delta__heatmap" style="--heatmap-columns:${heatmapColumns}" role="img" aria-label="Daily word additions and removals for the last ${daily.length} days">${leadingCells}${cells}</div>
      <div class="word-delta__legend" aria-label="Heatmap legend">
        <span><i class="word-delta__legend-chip word-delta__legend-chip--positive"></i>Net additions</span>
        <span><i class="word-delta__legend-chip word-delta__legend-chip--negative"></i>Net removals</span>
        <span><i class="word-delta__legend-chip word-delta__legend-chip--mixed"></i>Mixed edits</span>
      </div>
      <div class="word-delta__subtitle">Words added and removed, last 30 days</div>
      ${lineGraph}
      <div class="word-delta__date-axis" aria-hidden="true">
        <span>${escapeHtml(shortDate(graphDaily[0]?.date))}</span>
        <span>${escapeHtml(shortDate(graphDaily[Math.floor(graphDaily.length / 2)]?.date))}</span>
        <span>${escapeHtml(shortDate(graphDaily[graphDaily.length - 1]?.date))}</span>
      </div>
      <div class="word-delta__legend" aria-label="Line graph legend">
        <span><i class="word-delta__legend-line word-delta__legend-line--added"></i>Added</span>
        <span><i class="word-delta__legend-line word-delta__legend-line--removed"></i>Removed</span>
      </div>
      <div class="word-delta__summary">
        <span>${formatNumber(totals.added)} added</span>
        <span>${formatNumber(totals.removed)} removed</span>
        <span>${formatSigned(totals.net)} net</span>
      </div>
    `);
  }

  function renderHeatmapMonthLabels(daily, firstDayOffset, columns) {
    const labels = Array.from({ length: columns }, () => "");
    let previousMonth = "";
    daily.forEach((day, index) => {
      const date = new Date(`${day.date}T00:00:00`);
      const month = date.toLocaleDateString(undefined, { month: "short" });
      const column = Math.floor((firstDayOffset + index) / 7);
      if (month !== previousMonth && column < labels.length) {
        labels[column] = month;
        previousMonth = month;
      }
    });
    return labels.map((label) => `<span>${escapeHtml(label)}</span>`).join("");
  }

  function shortDate(dateString) {
    if (!dateString) return "";
    return new Date(`${dateString}T00:00:00`).toLocaleDateString(undefined, { month: "short", day: "numeric" });
  }

  function responsiveDays(element, requestedDays) {
    const width = element.getBoundingClientRect().width || element.clientWidth || 320;
    const approximateCell = 18;
    const availableWeeks = Math.max(2, Math.floor(width / approximateCell));
    const visible = Math.max(14, Math.min(requestedDays, availableWeeks * 7));
    return Math.min(requestedDays, visible);
  }

  function renderWordDeltaLineGraph(daily) {
    const width = 100;
    const height = 72;
    const baseline = 36;
    const max = Math.max(1, ...daily.map((day) => Math.max(Number(day.words_added || 0), Math.abs(Number(day.words_removed || 0)))));
    const xFor = (index) => daily.length <= 1 ? width / 2 : index / (daily.length - 1) * width;
    const yAdded = (day) => baseline - (Number(day.words_added || 0) / max * 28);
    const yRemoved = (day) => baseline + (Math.abs(Number(day.words_removed || 0)) / max * 28);
    const addedPoints = daily.map((day, index) => `${xFor(index).toFixed(2)},${yAdded(day).toFixed(2)}`).join(" ");
    const removedPoints = daily.map((day, index) => `${xFor(index).toFixed(2)},${yRemoved(day).toFixed(2)}`).join(" ");
    const addedArea = `M 0 ${baseline} ${daily.map((day, index) => `L ${xFor(index).toFixed(2)} ${yAdded(day).toFixed(2)}`).join(" ")} L ${width} ${baseline} Z`;
    const removedArea = `M 0 ${baseline} ${daily.map((day, index) => `L ${xFor(index).toFixed(2)} ${yRemoved(day).toFixed(2)}`).join(" ")} L ${width} ${baseline} Z`;
    const hitPoints = daily.map((day, index) => {
      const x = xFor(index).toFixed(2);
      const added = Number(day.words_added || 0);
      const removed = Number(day.words_removed || 0);
      const label = `${day.date}: ${formatNumber(added)} added, ${formatNumber(removed)} removed`;
      return `<circle class="word-delta__hit-point" cx="${x}" cy="${baseline}" r="2.2" data-tooltip="${escapeHtml(label)}" aria-label="${escapeHtml(label)}" tabindex="0"></circle>`;
    }).join("");
    return `
      <svg class="word-delta__line-chart" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" role="img" aria-label="Point graph of words added and removed by day">
        <line class="word-delta__axis" x1="0" y1="${baseline}" x2="${width}" y2="${baseline}"></line>
        <path class="word-delta__area word-delta__area--added" d="${addedArea}"></path>
        <path class="word-delta__area word-delta__area--removed" d="${removedArea}"></path>
        <polyline class="word-delta__line word-delta__line--added" points="${addedPoints}"></polyline>
        <polyline class="word-delta__line word-delta__line--removed" points="${removedPoints}"></polyline>
        ${hitPoints}
      </svg>
    `;
  }

  function dateRange(days) {
    const dates = [];
    const cursor = new Date();
    cursor.setHours(0, 0, 0, 0);
    cursor.setDate(cursor.getDate() - days + 1);
    for (let index = 0; index < days; index += 1) {
      dates.push(cursor.toISOString().slice(0, 10));
      cursor.setDate(cursor.getDate() + 1);
    }
    return dates;
  }

  function renderProjects(element, data) {
    let projects = data.projects || [];
    const projectId = element.dataset.project;
    if (!toBool(element.dataset.all)) {
      projects = projects.filter((project) => project.id === projectId);
    }
    if (!projects.length) {
      element.innerHTML = renderShell("Project Progress", "", '<p class="writing-dashboard__empty">No project progress data available.</p>');
      return;
    }
    const list = projects.map(renderProject).join("");
    element.innerHTML = renderShell("Project Progress", "", `
      <div class="project-progress__list">${list}</div>
      <div class="project-progress__legend" aria-label="Progress legend">
        <span class="project-progress__legend-item"><span class="project-progress__swatch" style="--swatch: var(--wd-missing)"></span>Missing</span>
        <span class="project-progress__legend-item"><span class="project-progress__swatch" style="--swatch: var(--wd-draft)"></span>Draft</span>
        <span class="project-progress__legend-item"><span class="project-progress__swatch" style="--swatch: var(--wd-published)"></span>Published</span>
      </div>
    `);
  }

  function renderProject(project) {
    const target = Number(project.target_words_per_chapter || 3000);
    const chapters = project.chapters || [];
    const published = chapters.filter((chapter) => chapter.status === "published").length;
    const expected = Number(project.expected_chapters || chapters.filter((chapter) => !chapter.is_appendix).length || chapters.length);
    const visibleChapters = collapseTrailingMissing(chapters);
    const segments = visibleChapters.map((chapter) => renderSegment(chapter, target)).join("");
    return `
      <article class="project-progress__item">
        <div class="project-progress__summary">
          <h4 class="project-progress__name">${escapeHtml(project.title || project.id)}</h4>
          <span class="project-progress__counts">${formatNumber(project.word_count)} words, ${published}/${expected} published</span>
        </div>
        <div class="project-progress__bar" role="img" aria-label="${escapeHtml(project.title || project.id)} progress">${segments}</div>
      </article>
    `;
  }

  function collapseTrailingMissing(chapters) {
    const appendixStart = chapters.findIndex((chapter) => chapter.is_appendix);
    const mainChapters = appendixStart === -1 ? chapters : chapters.slice(0, appendixStart);
    const appendices = appendixStart === -1 ? [] : chapters.slice(appendixStart);
    let tailStart = mainChapters.length;
    while (tailStart > 0 && (mainChapters[tailStart - 1].status || "missing") === "missing") {
      tailStart -= 1;
    }
    if (tailStart === mainChapters.length) return chapters;
    const tail = mainChapters.slice(tailStart);
    return [
      ...mainChapters.slice(0, tailStart),
      {
        index: tail[0].index,
        number: tail[0].number,
        is_missing_tail: true,
        missing_count: tail.length,
        status: "missing",
        word_count: 0,
      },
      ...appendices
    ];
  }

  function renderSegment(chapter, target) {
    const status = chapter.status || "missing";
    const count = Number(chapter.word_count || 0);
    const fill = status === "draft" ? Math.max(4, Math.min(100, count / target * 100)) : 100;
    const tailStyle = chapter.is_missing_tail ? `--tail-grow:${chapter.missing_count}` : "";
    const titleParts = [
      chapter.is_missing_tail ? `Chapters ${chapter.number}-${chapter.number + chapter.missing_count - 1}` : chapter.is_appendix ? "Appendix" : `Chapter ${chapter.number || chapter.index}`,
      status,
      `${formatNumber(count)} words`
    ];
    if (chapter.title) titleParts.push(chapter.title);
    return `<span class="project-progress__segment project-progress__segment--${escapeHtml(status)}${chapter.is_appendix ? " project-progress__segment--appendix" : ""}${chapter.is_missing_tail ? " project-progress__segment--missing-tail" : ""}" style="--fill:${fill}%;${tailStyle}" title="${escapeHtml(titleParts.join(" - "))}"></span>`;
  }

  function generatedMeta(data) {
    return data.generated_at ? `Updated ${data.generated_at.slice(0, 10)}` : "";
  }

  function showError(element, error) {
    element.innerHTML = `<p class="writing-dashboard__error">${escapeHtml(error.message || "Could not render writing dashboard.")}</p>`;
  }

  function initTooltips() {
    if (document.querySelector(".writing-dashboard-tooltip")) return;
    const tooltip = document.createElement("div");
    tooltip.className = "writing-dashboard-tooltip";
    document.body.appendChild(tooltip);

    const show = (event) => {
      const target = event.target.closest("[data-tooltip]");
      if (!target) return;
      tooltip.textContent = target.dataset.tooltip || "";
      tooltip.classList.add("is-visible");
      move(event, target);
    };
    const hide = () => tooltip.classList.remove("is-visible");
    const move = (event, target = null) => {
      const point = event.touches?.[0] || event;
      if (typeof point.clientX === "number" && typeof point.clientY === "number") {
        tooltip.style.left = `${point.clientX}px`;
        tooltip.style.top = `${point.clientY}px`;
        return;
      }
      const rect = target?.getBoundingClientRect();
      if (rect) {
        tooltip.style.left = `${rect.left + rect.width / 2}px`;
        tooltip.style.top = `${rect.top}px`;
      }
    };

    document.addEventListener("pointerover", show);
    document.addEventListener("pointermove", (event) => {
      if (tooltip.classList.contains("is-visible")) move(event);
    });
    document.addEventListener("pointerout", (event) => {
      if (event.target.closest("[data-tooltip]")) hide();
    });
    document.addEventListener("focusin", show);
    document.addEventListener("focusout", hide);
  }

  function init() {
    initTooltips();
    document.querySelectorAll("[data-writing-widget]").forEach((element) => {
      const type = element.dataset.writingWidget;
      const url = type === "project-progress" ? element.dataset.projectsUrl : element.dataset.statsUrl;
      fetchJson(url)
        .then((data) => {
          if (type === "activity") renderActivity(element, data);
          if (type === "corpus") renderCorpus(element, data);
          if (type === "word-delta") setupResponsiveWordDelta(element, data);
          if (type === "project-progress") renderProjects(element, data);
        })
        .catch((error) => showError(element, error));
    });
  }

  function setupResponsiveWordDelta(element, data) {
    let lastDays = 0;
    const render = () => {
      const nextDays = responsiveDays(element, Math.max(1, Number.parseInt(element.dataset.days || "30", 10)));
      if (nextDays === lastDays && element.querySelector(".word-delta__heatmap")) return;
      lastDays = nextDays;
      renderWordDelta(element, data);
    };
    render();
    if ("ResizeObserver" in window) {
      const observer = new ResizeObserver(render);
      observer.observe(element);
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
}());
