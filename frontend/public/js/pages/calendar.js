// frontend/public/js/pages/calendar.js

import { sampleFarm, emptyFarm } from '../data/sample-farm.js';
import { sampleCalendar, emptyCalendar } from '../data/sample-calendar.js';
import { CROPS, GROWTH_STAGES, REMINDER_OPTIONS, SEASONS } from '../data/farm-options.js';
import { pickDemo } from '../utils/demo.js';
import { currentCycle, fieldLabel } from '../utils/farm.js';
import { showToast } from '../utils/toast.js';
import {
  setFieldError,
  clearFieldErrors,
  focusFirstInvalid,
  bindLiveErrorClearing,
} from '../utils/form.js';
import {
  addDays,
  daysBetween,
  formatClock,
  formatNumericDate,
  formatRange,
  formatShortDate,
  parseISODate,
  startOfDay,
  startOfWeek,
  toISODate,
} from '../utils/dates.js';

/** Finished tasks count toward a week's completion. */
const FINISHED = new Set(['done', 'skipped']);
const TIMED_REMINDERS = new Set(['at_start', '30_min', '1_hour']);

const MESSAGES = {
  noFarm: 'No fields yet. Set up your farm to get a crop calendar.',
  noCycle: 'Nothing is planted on this field yet.',
  noTasks: 'No tasks match.',
  noCompleted: 'No completed tasks yet.',
  titleRequired: 'Enter a task name.',
  fieldRequired: 'Choose the field for this task.',
  stageRequired: 'Choose the crop stage.',
  dateRequired: 'Enter the date.',
  timeForReminder: 'Set a start time for this reminder.',
  saved: 'Task saved.',
  skipped: 'Task skipped.',
  deleted: 'Task deleted.',
  deleteConfirm: (title) => `Delete "${title}"?`,
  moved: (date) => `Task moved to ${formatShortDate(date)}.`,
};

/**
 * The calendar screens read and change the sample data in memory (check, skip, reschedule,
 * add, edit, delete); changes last until the page reloads. The chosen field is shared.
 */
const shared = { fieldId: null };

function data() {
  return { farm: pickDemo(sampleFarm, emptyFarm), calendar: pickDemo(sampleCalendar, emptyCalendar) };
}

function cycleForField(farm, fieldId) {
  return currentCycle(farm, fieldId);
}

function labelOf(options, value) {
  return options.find((option) => option.value === value)?.label ?? value;
}

function cropIcon(cropName) {
  const crop = CROPS.find((c) => c.label === cropName);
  return `#${crop?.icon ?? 'icon-crop-rice'}`;
}

/** Tasks of one cycle, by date then start time. */
function tasksOf(calendar, cycleId) {
  return calendar.activities
    .filter((activity) => activity.cycle_id === cycleId)
    .sort(byDateTime);
}

function byDateTime(a, b) {
  return a.scheduled_date.localeCompare(b.scheduled_date) || (a.start_time ?? '').localeCompare(b.start_time ?? '');
}

/** CALENDAR_TEMPLATE_TASK.week_no: week relative to planting; negative before it. */
function weekNo(activity, cycle) {
  return Math.floor(daysBetween(parseISODate(cycle.planting_date), parseISODate(activity.scheduled_date)) / 7);
}

function setDone(activity, done) {
  activity.status = done ? 'done' : 'pending';
  activity.completed_at = done ? new Date().toISOString() : null;
}

/** Wires a task checkbox: ticks the task, redraws, and keeps focus on the same task's checkbox. */
function bindCheck(check, task, scope, render) {
  check.dataset.activity = String(task.activity_id);
  check.checked = task.status === 'done';
  check.addEventListener('change', () => {
    setDone(task, check.checked);
    render();
    scope.querySelector(`[data-check][data-activity="${task.activity_id}"]`)?.focus();
  });
}

function syncFieldSelection(farm) {
  if (!farm.fields.some((field) => field.field_id === shared.fieldId)) {
    shared.fieldId = farm.fields[0]?.field_id ?? null;
  }
}

function formatPesoShort(value) {
  if (value >= 1000) return `₱${(value / 1000).toLocaleString('en-PH', { maximumFractionDigits: 1 })}k`;
  return `₱${value.toLocaleString('en-PH')}`;
}

function showEmpty(view, message, { setup = false } = {}) {
  view.querySelector('[data-empty]').hidden = false;
  view.querySelector('[data-empty-text]').textContent = message;
  view.querySelector('[data-empty-setup]').hidden = !setup;
}

/* ---------- Crop Calendar ---------- */

function mountCalendar() {
  const view = document.querySelector('[data-view="calendar"]');
  const picker = view.querySelector('[data-field-picker]');
  const content = view.querySelector('[data-content]');
  const month = view.querySelector('[data-month]');
  const strip = view.querySelector('[data-day-strip]');
  const dayList = view.querySelector('[data-day-list]');
  const dayEmpty = view.querySelector('[data-day-empty]');
  const weekList = view.querySelector('[data-week-list]');
  const weekEmpty = view.querySelector('[data-week-empty]');
  const weekMore = view.querySelector('[data-week-more]');
  const tpl = (name) => view.querySelector(`template[data-${name}-tpl]`).content.firstElementChild;
  const openWeeks = new Set();
  const NEARBY_WEEKS = 3;
  let selectedDay = startOfDay();
  let showAllWeeks = false;

  function renderSummary(cycle, calendar) {
    const planted = parseISODate(cycle.planting_date);
    const harvest = parseISODate(cycle.expected_harvest_date);
    const seasonDays = Math.max(1, daysBetween(planted, harvest));
    const completion = Math.min(100, Math.max(0, Math.round((daysBetween(planted, new Date()) / seasonDays) * 100)));
    const estimate = calendar.estimates.find((e) => e.cycle_id === cycle.cycle_id);
    const value = estimate ? estimate.predicted_total_t * 1000 * estimate.price_php_per_kg : null;
    const stat = (name) => view.querySelector(`[data-stat="${name}"]`);

    view.querySelector('[data-crop-icon]').setAttribute('href', cropIcon(cycle.crop_name));
    view.querySelector('[data-schedule-title]').textContent = `${cycle.crop_name} Crop Schedule`;
    view.querySelector('[data-schedule-season]').textContent = `Season: ${labelOf(SEASONS, cycle.season)}`;
    stat('completion').textContent = `${completion}%`;
    stat('value').textContent = value == null ? '—' : formatPesoShort(value);
    stat('planted').textContent = formatNumericDate(planted);
    stat('harvest').textContent = `~${Math.round(seasonDays / 30)} months`;
  }

  function renderMonths(tasks, cycle) {
    const dates = [parseISODate(cycle.planting_date), ...tasks.map((t) => parseISODate(t.scheduled_date))];
    const first = new Date(Math.min(...dates));
    const last = new Date(Math.max(...dates, selectedDay));
    const options = [];
    for (let d = new Date(first.getFullYear(), first.getMonth(), 1); d <= last; d.setMonth(d.getMonth() + 1)) {
      options.push(new Option(d.toLocaleDateString('en-PH', { month: 'long', year: 'numeric' }), toISODate(d).slice(0, 7)));
    }
    month.replaceChildren(...options);
    month.value = toISODate(selectedDay).slice(0, 7);
  }

  function renderDays(tasks) {
    const taskDays = new Set(tasks.map((t) => t.scheduled_date));
    const weekStart = startOfWeek(selectedDay);
    const today = toISODate(startOfDay());
    const chips = [];
    for (let i = 0; i < 7; i += 1) {
      const day = addDays(weekStart, i);
      const iso = toISODate(day);
      const chip = tpl('day').cloneNode(true);
      chip.querySelector('[data-dow]').textContent = day.toLocaleDateString('en-PH', { weekday: 'short' });
      chip.querySelector('[data-date]').textContent = String(day.getDate());
      chip.querySelector('[data-dot]').hidden = !taskDays.has(iso);
      chip.setAttribute('aria-pressed', String(iso === toISODate(selectedDay)));
      chip.setAttribute('aria-label', day.toLocaleDateString('en-PH', { weekday: 'long', month: 'long', day: 'numeric' }));
      chip.classList.toggle('is-today', iso === today);
      chip.addEventListener('click', () => {
        selectedDay = day;
        render();
      });
      chips.push(chip);
    }
    strip.replaceChildren(...chips);

    const dayTasks = tasks.filter((t) => t.scheduled_date === toISODate(selectedDay));
    dayList.replaceChildren(...dayTasks.map((task) => {
      const item = tpl('day-task').cloneNode(true);
      const check = item.querySelector('[data-check]');
      item.querySelector('[data-time]').textContent = formatClock(task.start_time) || 'Any time';
      item.querySelector('[data-title]').textContent = task.title;
      item.classList.toggle('is-done', FINISHED.has(task.status));
      bindCheck(check, task, dayList, render);
      return item;
    }));
    dayEmpty.hidden = dayTasks.length > 0;
  }

  function renderWeeks(tasks, cycle) {
    const groups = new Map();
    for (const task of tasks) {
      const no = weekNo(task, cycle);
      if (!groups.has(no)) groups.set(no, []);
      groups.get(no).push(task);
    }
    const weeks = [...groups.keys()].sort((a, b) => a - b);
    const planted = parseISODate(cycle.planting_date);
    const currentWeek = Math.floor(daysBetween(planted, new Date()) / 7);
    const key = (no) => `${cycle.cycle_id}:${no}`;
    if (![...openWeeks].some((k) => k.startsWith(`${cycle.cycle_id}:`))) openWeeks.add(key(currentWeek));

    // By default show last week, this week and next week (or the nearest weeks that have tasks).
    const firstNearby = weeks.findIndex((no) => no >= currentWeek - 1);
    const startAt = Math.max(0, Math.min(firstNearby === -1 ? weeks.length : firstNearby, weeks.length - NEARBY_WEEKS));
    const shown = showAllWeeks ? weeks : weeks.slice(startAt, startAt + NEARBY_WEEKS);
    weekMore.hidden = weeks.length <= NEARBY_WEEKS;
    weekMore.textContent = showAllWeeks ? 'Show fewer weeks' : `Show all ${weeks.length} weeks`;
    weekMore.setAttribute('aria-expanded', String(showAllWeeks));

    weekList.replaceChildren(...shown.map((no) => {
      const items = groups.get(no);
      const finished = items.filter((t) => FINISHED.has(t.status)).length;
      const pct = Math.round((finished / items.length) * 100);
      const start = addDays(planted, no * 7);
      const card = tpl('week').cloneNode(true);
      const toggle = card.querySelector('[data-toggle]');
      const list = card.querySelector('[data-tasks]');
      const open = openWeeks.has(key(no));

      // Weeks are counted from the first week of the schedule, so weeks without tasks keep their number.
      card.querySelector('[data-no]').textContent = `Week ${no - weeks[0] + 1}`;
      card.querySelector('[data-stage]').textContent = labelOf(GROWTH_STAGES, items[0].growth_stage);
      card.querySelector('[data-range]').textContent = formatRange(start, addDays(start, 6));
      card.querySelector('[data-pct]').textContent = `${pct}%`;
      card.querySelector('[data-bar]').style.width = `${pct}%`;
      card.querySelector('[data-done-icon]').hidden = pct < 100;
      card.classList.toggle('is-current', no === currentWeek);
      toggle.setAttribute('aria-expanded', String(open));
      toggle.querySelector('[data-toggle-label]').textContent = open ? 'Hide tasks' : 'Show tasks';
      list.hidden = !open;
      list.replaceChildren(...items.map((task) => checkRow(task)));
      toggle.addEventListener('click', () => {
        if (openWeeks.has(key(no))) openWeeks.delete(key(no));
        else openWeeks.add(key(no));
        render();
      });
      return card;
    }));
    weekEmpty.hidden = tasks.length > 0;
  }

  function checkRow(task) {
    const row = tpl('check').cloneNode(true);
    const check = row.querySelector('[data-check]');
    const tag = row.querySelector('[data-tag]');
    row.querySelector('[data-title]').textContent = task.title;
    row.classList.toggle('is-done', FINISHED.has(task.status));
    tag.hidden = task.status !== 'skipped';
    tag.textContent = 'Skipped';
    bindCheck(check, task, weekList, render);
    return row;
  }

  function render() {
    const { farm, calendar } = data();
    view.querySelector('[data-empty]').hidden = true;
    syncFieldSelection(farm);
    picker.replaceChildren(...farm.fields.map((field) => new Option(fieldLabel(farm, field), String(field.field_id))));
    picker.value = String(shared.fieldId);
    picker.disabled = farm.fields.length === 0;

    if (!farm.fields.length) {
      content.hidden = true;
      showEmpty(view, MESSAGES.noFarm, { setup: true });
      return;
    }
    const cycle = cycleForField(farm, shared.fieldId);
    if (!cycle) {
      content.hidden = true;
      showEmpty(view, MESSAGES.noCycle);
      return;
    }

    const tasks = tasksOf(calendar, cycle.cycle_id);
    content.hidden = false;
    renderSummary(cycle, calendar);
    renderMonths(tasks, cycle);
    renderDays(tasks);
    renderWeeks(tasks, cycle);
  }

  picker.addEventListener('change', () => {
    shared.fieldId = Number(picker.value);
    selectedDay = startOfDay();
    showAllWeeks = false;
    render();
  });

  weekMore.addEventListener('click', () => {
    showAllWeeks = !showAllWeeks;
    render();
  });

  month.addEventListener('change', () => {
    const [year, mon] = month.value.split('-').map(Number);
    const { farm, calendar } = data();
    const cycle = cycleForField(farm, shared.fieldId);
    const first = tasksOf(calendar, cycle.cycle_id).find((t) => t.scheduled_date.startsWith(month.value));
    selectedDay = first ? parseISODate(first.scheduled_date) : new Date(year, mon - 1, 1);
    render();
  });

  return {
    enter() {
      selectedDay = startOfDay();
      render();
    },
  };
}

/* ---------- Manage All Tasks ---------- */

function mountTasks(router) {
  const view = document.querySelector('[data-view="tasks"]');
  const search = view.querySelector('[data-task-search]');
  const chipAll = view.querySelector('[data-chip-all]');
  const chipField = view.querySelector('[data-chip-field]');
  const chipCompleted = view.querySelector('[data-chip-completed]');
  const groupsEl = view.querySelector('[data-task-groups]');
  const addTask = view.querySelector('[data-add-task]');
  const reschedule = view.querySelector('[data-reschedule]');
  const tpl = (name) => view.querySelector(`template[data-${name}-tpl]`).content.firstElementChild;
  const filters = { query: '', fieldId: null, completed: false };
  let rescheduling = null;

  function closeMenus(except) {
    view.querySelectorAll('[data-menu]').forEach((menu) => {
      if (menu === except) return;
      menu.hidden = true;
      menu.closest('.task-menu').querySelector('[data-menu-btn]').setAttribute('aria-expanded', 'false');
    });
  }

  function taskCard(entry, showField) {
    const { task, field, cycle } = entry;
    const card = tpl('task').cloneNode(true);
    const check = card.querySelector('[data-check]');
    const tag = card.querySelector('[data-tag]');
    const menuBtn = card.querySelector('[data-menu-btn]');
    const menu = card.querySelector('[data-menu]');
    const date = parseISODate(task.scheduled_date);
    const meta = [showField ? `${field.field_name} · ${cycle.crop_name}` : null, formatClock(task.start_time)];

    card.querySelector('[data-title]').textContent = task.title;
    card.querySelector('[data-date]').textContent = formatShortDate(date).toUpperCase();
    card.querySelector('[data-desc]').textContent = task.description ?? '';
    card.querySelector('[data-desc]').hidden = !task.description;
    card.querySelector('[data-meta]').textContent = meta.filter(Boolean).join(' · ');
    card.querySelector('[data-check-label]').textContent = `Mark "${task.title}" as done`;
    card.classList.toggle('is-done', FINISHED.has(task.status));
    bindCheck(check, task, groupsEl, render);
    tag.hidden = task.status !== 'skipped' && task.status !== 'rescheduled';
    tag.textContent = task.status === 'skipped' ? 'Skipped' : 'Rescheduled';
    menuBtn.setAttribute('aria-label', `More actions for "${task.title}"`);
    card.querySelector('[data-action="skip"]').hidden = task.status === 'skipped';

    menuBtn.addEventListener('click', (event) => {
      event.stopPropagation();
      const open = menu.hidden;
      closeMenus(menu);
      menu.hidden = !open;
      menuBtn.setAttribute('aria-expanded', String(open));
      if (open) menu.querySelector('button:not([hidden])')?.focus();
    });
    menu.addEventListener('click', (event) => {
      const action = event.target.closest('[data-action]')?.dataset.action;
      if (!action) return;
      closeMenus();
      runAction(action, task);
    });
    return card;
  }

  function runAction(action, task) {
    const { calendar } = data();
    if (action === 'skip') {
      task.status = 'skipped';
      task.completed_at = null;
      showToast(MESSAGES.skipped);
      render();
    } else if (action === 'reschedule') {
      rescheduling = task;
      reschedule.value = task.scheduled_date;
      if (typeof reschedule.showPicker === 'function') {
        try {
          reschedule.showPicker();
          return;
        } catch {
          /* picker blocked; fall through to the edit form */
        }
      }
      router.navigate('task-new', { state: { activityId: task.activity_id } });
    } else if (action === 'edit') {
      router.navigate('task-new', { state: { activityId: task.activity_id } });
    } else if (action === 'delete' && window.confirm(MESSAGES.deleteConfirm(task.title))) {
      calendar.activities.splice(calendar.activities.indexOf(task), 1);
      showToast(MESSAGES.deleted);
      render();
    }
  }

  reschedule.addEventListener('change', () => {
    const date = parseISODate(reschedule.value);
    if (!rescheduling || !date) return;
    rescheduling.scheduled_date = reschedule.value;
    rescheduling.status = 'rescheduled';
    rescheduling.completed_at = null;
    rescheduling = null;
    showToast(MESSAGES.moved(date));
    render();
  });

  /** Groups of { title, week, entries } in the order they are shown. */
  function groupTasks(entries) {
    if (filters.completed) {
      const done = entries.filter((e) => FINISHED.has(e.task.status)).sort((a, b) => byDateTime(b.task, a.task));
      return done.length ? [{ title: 'Completed Tasks', week: '', entries: done }] : [];
    }

    const open = entries.filter((e) => !FINISHED.has(e.task.status)).sort((a, b) => byDateTime(a.task, b.task));
    const today = startOfDay();
    // One field: weeks of its season, counted from planting (like the weekly timeline).
    // All plots: calendar weeks from Sunday, since each field was planted on a different day.
    const seasonCycle = filters.fieldId != null ? entries[0]?.cycle : null;
    const planted = seasonCycle ? parseISODate(seasonCycle.planting_date) : null;
    const seasonWeekStart = (date) => addDays(planted, Math.floor(daysBetween(planted, date) / 7) * 7);
    const weekStartOf = (e) => (seasonCycle
      ? seasonWeekStart(parseISODate(e.task.scheduled_date))
      : startOfWeek(parseISODate(e.task.scheduled_date)));
    const currentStart = seasonCycle ? seasonWeekStart(today) : startOfWeek(today);
    const firstWeek = seasonCycle ? Math.min(...entries.map((e) => weekNo(e.task, e.cycle))) : 0;

    const groups = [];
    const overdue = open.filter((e) => weekStartOf(e) < currentStart);
    if (overdue.length) groups.push({ title: 'Overdue', week: '', entries: overdue });

    let upcomingTitled = false;
    for (const entry of open.filter((e) => weekStartOf(e) >= currentStart)) {
      const start = weekStartOf(entry);
      const last = groups[groups.length - 1];
      if (last?.start?.getTime() === start.getTime()) {
        last.entries.push(entry);
        continue;
      }
      const isCurrent = start.getTime() === currentStart.getTime();
      const range = formatRange(start, addDays(start, 6));
      let week;
      if (seasonCycle) week = `Week ${weekNo(entry.task, entry.cycle) - firstWeek + 1} · ${range}`;
      else if (isCurrent) week = `This week · ${range}`;
      else if (daysBetween(currentStart, start) === 7) week = `Next week · ${range}`;
      else week = range;
      let title = '';
      if (isCurrent) title = 'Current Tasks';
      else if (!upcomingTitled) title = 'Upcoming Tasks';
      if (!isCurrent) upcomingTitled = true;
      groups.push({ title, week, start, entries: [entry] });
    }
    return groups;
  }

  function render() {
    const { farm, calendar } = data();
    const empty = view.querySelector('[data-empty]');
    empty.hidden = true;

    chipField.replaceChildren(
      new Option('Field', ''),
      ...farm.fields.map((field) => new Option(fieldLabel(farm, field), String(field.field_id))),
    );
    if (!farm.fields.some((f) => f.field_id === filters.fieldId)) filters.fieldId = null;
    chipField.value = filters.fieldId == null ? '' : String(filters.fieldId);
    chipAll.setAttribute('aria-pressed', String(filters.fieldId == null));
    chipField.closest('.chip').classList.toggle('is-active', filters.fieldId != null);
    chipCompleted.setAttribute('aria-pressed', String(filters.completed));
    addTask.hidden = farm.fields.length === 0;

    if (!farm.fields.length) {
      groupsEl.replaceChildren();
      showEmpty(view, MESSAGES.noFarm, { setup: true });
      return;
    }

    const query = filters.query.trim().toLowerCase();
    const entries = calendar.activities
      .map((task) => {
        const cycle = farm.cycles.find((c) => c.cycle_id === task.cycle_id);
        const field = cycle && farm.fields.find((f) => f.field_id === cycle.field_id);
        return field ? { task, cycle, field } : null;
      })
      .filter(Boolean)
      .filter((e) => filters.fieldId == null || e.field.field_id === filters.fieldId)
      .filter((e) => !query || `${e.task.title} ${e.task.description ?? ''}`.toLowerCase().includes(query));

    const groups = groupTasks(entries);
    groupsEl.replaceChildren(...groups.map((group) => {
      const el = tpl('group').cloneNode(true);
      const title = el.querySelector('[data-group-title]');
      const week = el.querySelector('[data-group-week]');
      title.textContent = group.title;
      title.hidden = !group.title;
      week.textContent = group.week;
      week.hidden = !group.week;
      el.querySelector('[data-group-list]').replaceChildren(
        ...group.entries.map((entry) => taskCard(entry, filters.fieldId == null)),
      );
      return el;
    }));
    if (!groups.length) showEmpty(view, filters.completed ? MESSAGES.noCompleted : MESSAGES.noTasks);
  }

  search.addEventListener('input', () => {
    filters.query = search.value;
    render();
  });
  chipAll.addEventListener('click', () => {
    filters.fieldId = null;
    render();
  });
  chipField.addEventListener('change', () => {
    filters.fieldId = chipField.value ? Number(chipField.value) : null;
    if (filters.fieldId != null) shared.fieldId = filters.fieldId;
    render();
  });
  chipCompleted.addEventListener('click', () => {
    filters.completed = !filters.completed;
    render();
  });
  document.addEventListener('click', (event) => {
    if (!view.hidden && !event.target.closest('.task-menu')) closeMenus();
  });
  view.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') closeMenus();
  });

  return {
    enter({ from, state } = {}) {
      if (from === 'calendar') filters.fieldId = null;
      // After saving, show the saved task even if another field was filtered.
      if (state?.savedFieldId != null && filters.fieldId != null) filters.fieldId = state.savedFieldId;
      if (state?.savedFieldId != null) filters.completed = false;
      render();
      // The router focuses the heading after onEnter, so focus the search box afterwards.
      if (state?.focusSearch) requestAnimationFrame(() => search.focus());
    },
    leave() {
      closeMenus();
    },
  };
}

/* ---------- New / edit farm task ---------- */

function mountTaskForm(router) {
  const view = document.querySelector('[data-view="task-new"]');
  const form = document.getElementById('task-form');
  const heading = view.querySelector('[data-form-title]');
  const saveButton = view.querySelector('[data-save-label]');
  const {
    title,
    field_id: fieldSelect,
    growth_stage: stage,
    scheduled_date: date,
    start_time: time,
    reminder,
    description,
  } = form.elements;
  let editing = null;

  for (const option of GROWTH_STAGES) stage.add(new Option(option.label, option.value));
  for (const option of REMINDER_OPTIONS) reminder.add(new Option(option.label, option.value));
  bindLiveErrorClearing(form);

  function validate(farm) {
    const name = title.value.trim().replace(/\s+/g, ' ');
    const fieldId = Number(fieldSelect.value);
    const cycle = cycleForField(farm, fieldId);

    if (!name) setFieldError(title, MESSAGES.titleRequired);
    if (!fieldSelect.value || !cycle) setFieldError(fieldSelect, MESSAGES.fieldRequired);
    if (!stage.value) setFieldError(stage, MESSAGES.stageRequired);
    if (!parseISODate(date.value)) setFieldError(date, MESSAGES.dateRequired);
    if (TIMED_REMINDERS.has(reminder.value) && !time.value) setFieldError(reminder, MESSAGES.timeForReminder);

    if (form.querySelector('[aria-invalid="true"]')) return null;
    return {
      cycle_id: cycle.cycle_id,
      title: name,
      description: description.value.trim() || null,
      growth_stage: stage.value,
      scheduled_date: date.value,
      start_time: time.value || null,
      reminder: reminder.value,
    };
  }

  form.addEventListener('submit', (event) => {
    event.preventDefault();
    clearFieldErrors(form);
    const { farm, calendar } = data();
    const values = validate(farm);
    if (!values) {
      focusFirstInvalid(form);
      return;
    }

    if (editing) {
      Object.assign(editing, values);
    } else {
      const nextId = Math.max(0, ...calendar.activities.map((a) => a.activity_id)) + 1;
      calendar.activities.push({
        activity_id: nextId,
        template_task_id: null,
        status: 'pending',
        completed_at: null,
        ...values,
      });
    }
    shared.fieldId = Number(fieldSelect.value);
    showToast(MESSAGES.saved);
    router.navigate('tasks', { replace: true, state: { savedFieldId: shared.fieldId } });
  });

  view.querySelector('[data-cancel]').addEventListener('click', () => router.back('tasks'));

  router.route('task-new', {
    onEnter({ state } = {}) {
      const { farm, calendar } = data();
      editing = calendar.activities.find((a) => a.activity_id === state?.activityId) ?? null;
      form.reset();
      clearFieldErrors(form);
      syncFieldSelection(farm);
      fieldSelect.replaceChildren(
        new Option('Select field', ''),
        ...farm.fields.map((field) => new Option(fieldLabel(farm, field), String(field.field_id))),
      );

      heading.textContent = editing ? 'Edit Farm Task' : 'New Farm Task';
      saveButton.textContent = editing ? 'Save Changes' : 'Save Task';
      if (editing) {
        const cycle = farm.cycles.find((c) => c.cycle_id === editing.cycle_id);
        title.value = editing.title;
        fieldSelect.value = String(cycle?.field_id ?? '');
        stage.value = editing.growth_stage;
        date.value = editing.scheduled_date;
        time.value = editing.start_time ?? '';
        reminder.value = editing.reminder ?? 'none';
        description.value = editing.description ?? '';
      } else {
        fieldSelect.value = shared.fieldId == null ? '' : String(shared.fieldId);
        date.value = toISODate(startOfDay());
        reminder.value = 'none';
      }
    },
  });
}

/* ---------- Public entry ---------- */

export function mountCalendarPages(router) {
  const calendar = mountCalendar();
  const tasks = mountTasks(router);
  mountTaskForm(router);

  router.route('calendar', { onEnter: () => calendar.enter() });
  router.route('tasks', {
    onEnter: ({ from, state } = {}) => tasks.enter({ from, state }),
    onLeave: () => tasks.leave(),
  });

  document.querySelector('[data-view="calendar"] [data-search-tasks]').addEventListener('click', (event) => {
    event.preventDefault();
    router.navigate('tasks', { state: { focusSearch: true } });
  });
}
