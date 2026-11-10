// frontend/public/js/pages/calendar.js

/**
 * Crop Calendar, Manage All Tasks, and New / Edit Farm Task on the real API:
 * GET /farms/{farm_id}/fields (each field's current cycle), GET /cycles/{cycle_id}/activities,
 * GET /farms/{farm_id}/activities, POST /cycles/{cycle_id}/activities, PATCH and DELETE
 * /activities/{activity_id}. Weeks count from the sowing date: week 1 is the sowing day to
 * day 6. Completion is (done + skipped) ÷ all tasks. Dates are Philippine dates.
 */
import { activities as api, ApiError } from '../api/client.js';
import { CROPS, GROWTH_STAGES, SEASONS } from '../data/farm-options.js';
import { showToast } from '../utils/toast.js';
import {
  setFieldError,
  clearFieldErrors,
  focusFirstInvalid,
  bindLiveErrorClearing,
  setStatus,
  setBusy,
} from '../utils/form.js';
import {
  addDays,
  daysBetween,
  formatClock,
  formatNumericDate,
  formatRange,
  formatShortDate,
  parseISODate,
  philippineToday,
  toISODate,
} from '../utils/dates.js';
import { loadFirstFarm, newClientUuid } from './expenses.js';

const FINISHED = new Set(['done', 'skipped']);
const PAGE_SIZE = 200; // GET /farms/{farm_id}/activities allows at most 200 per page
const NEARBY_WEEKS = 3;

const MESSAGES = {
  noFarm: 'No fields yet. Set up your farm to get a crop calendar.',
  noCycle: 'Nothing is planted on this field yet.',
  noTasks: 'No tasks match.',
  noCompleted: 'No completed tasks yet.',
  noTaskFields: 'No crop is planted yet. Set up your farm or add a plot before adding tasks.',
  loadFailed: 'Your tasks could not be loaded. Check your connection and try again.',
  saveFailed: 'The task could not be saved. Check your connection and try again.',
  titleRequired: 'Enter a task name.',
  fieldRequired: 'Choose the field for this task.',
  dateRequired: 'Enter the date.',
  saved: 'Task saved.',
  done: 'Task marked as done.',
  undone: 'Task marked as not done.',
  skipped: 'Task skipped.',
  deleted: 'Task deleted.',
  chatbotSoon: 'Coming soon: ask the chatbot about your calendar.',
  deleteConfirm: (title) => `Delete "${title}"?`,
  // Error codes of the activity endpoints, as short plain messages.
  cycle_not_found: 'This crop cycle could not be found. Go back and try again.',
  activity_not_found: 'This task could not be found. It may have been deleted.',
  cycle_closed: 'This crop cycle is closed, so its tasks can no longer change.',
  client_uuid_taken: 'This task could not be saved. Try again.',
  date_out_of_range: 'Choose a date within 2 years of today.',
  not_editable: 'Only tasks you added can be renamed or moved to another stage.',
  generated_task: 'Tasks from the crop guide can be skipped, not deleted.',
  field_not_in_farm: 'This field is not on your farm.',
};

/** The field chosen on the Crop Calendar, shared with the task form. */
const shared = { fieldId: null };

function isSessionEnd(err) {
  return err instanceof ApiError && err.sessionEnded;
}

function errorMessage(err, fallback) {
  return (err instanceof ApiError && MESSAGES[err.code]) || fallback;
}

function labelOf(options, value) {
  return options.find((option) => option.value === value)?.label ?? value ?? '';
}

function cropIcon(cropName) {
  const crop = CROPS.find((c) => c.label.toLowerCase() === String(cropName).toLowerCase());
  return `#${crop?.icon ?? 'icon-crop-rice'}`;
}

/** 'HH:MM' from the API's 'HH:MM:SS'; '' when there is no time. */
function hhmm(time) {
  return time ? time.slice(0, 5) : '';
}

/** The last day of a task: end_date for a range, otherwise its date. */
function lastDay(task) {
  return task.end_date ?? task.scheduled_date;
}

/** Week of the season, counted from sowing: week 1 is the sowing day to day 6. */
function weekOf(dateISO, sowingISO) {
  return Math.floor(daysBetween(parseISODate(sowingISO), parseISODate(dateISO)) / 7) + 1;
}

function weekStart(no, sowingISO) {
  return addDays(parseISODate(sowingISO), (no - 1) * 7);
}

function weekLabel(no) {
  return no >= 1 ? `Week ${no}` : 'Before sowing';
}

function fieldOption(field) {
  const crop = field.current_cycle?.crop_name;
  return new Option(crop ? `${field.field_name} · ${crop}` : field.field_name, String(field.field_id));
}

function syncFieldSelection(fields) {
  if (!fields.some((field) => field.field_id === shared.fieldId)) {
    const planted = fields.find((field) => field.current_cycle) ?? fields[0];
    shared.fieldId = planted?.field_id ?? null;
  }
}

function showEmpty(view, message, { setup = false } = {}) {
  view.querySelector('[data-empty]').hidden = false;
  view.querySelector('[data-empty-text]').textContent = message;
  const setupLink = view.querySelector('[data-empty-setup]');
  if (setupLink) setupLink.hidden = !setup;
}

/** Marks a task done or not done from its checkbox, then reloads the screen. */
function bindCheck(check, task, reload, view) {
  check.dataset.activity = String(task.activity_id);
  check.checked = task.status === 'done';
  check.addEventListener('change', async () => {
    check.disabled = true;
    setStatus(view, '');
    try {
      await api.update(task.activity_id, { status: check.checked ? 'done' : 'pending' });
      await reload();
      view.querySelector(`[data-check][data-activity="${task.activity_id}"]`)?.focus();
    } catch (err) {
      if (isSessionEnd(err)) return;
      check.checked = !check.checked;
      check.disabled = false;
      setStatus(view, errorMessage(err, MESSAGES.saveFailed), 'error');
    }
  });
}

/** Reloads a screen when its tab becomes visible again, so a tab left open isn't stale. */
function reloadWhenVisible(view, reload) {
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible' && !view.hidden) reload();
  });
}

/* ---------- Crop Calendar ---------- */

function mountCalendar() {
  const view = document.querySelector('[data-view="calendar"]');
  const picker = view.querySelector('[data-field-picker]');
  const content = view.querySelector('[data-content]');
  const month = view.querySelector('[data-month]');
  const strip = view.querySelector('[data-day-strip]');
  const dayList = view.querySelector('[data-day-list]');
  const ongoingTitle = view.querySelector('[data-ongoing-title]');
  const ongoingList = view.querySelector('[data-ongoing-list]');
  const dayEmpty = view.querySelector('[data-day-empty]');
  const weekList = view.querySelector('[data-week-list]');
  const weekEmpty = view.querySelector('[data-week-empty]');
  const weekMore = view.querySelector('[data-week-more]');
  const tpl = (name) => view.querySelector(`template[data-${name}-tpl]`).content.firstElementChild;
  const openWeeks = new Set();
  let fields = [];
  let calendar = null; // { cycle, items } from GET /cycles/{cycle_id}/activities
  let selectedDay = philippineToday();
  let showAllWeeks = false;
  let requestId = 0;

  function renderSummary(cycle) {
    const stat = (name) => view.querySelector(`[data-stat="${name}"]`);
    view.querySelector('[data-crop-icon]').setAttribute('href', cropIcon(cycle.crop_name));
    view.querySelector('[data-schedule-title]').textContent = `${cycle.crop_name} Crop Schedule`;
    view.querySelector('[data-schedule-season]').textContent = `Season: ${labelOf(SEASONS, cycle.season)}`;
    stat('completion').textContent = `${cycle.completion_pct}%`;
    stat('value').textContent = 'Coming soon'; // needs yield estimation
    stat('planted').textContent = formatNumericDate(parseISODate(cycle.planting_date));
    stat('harvest').textContent = formatNumericDate(parseISODate(cycle.expected_harvest_date));
  }

  function renderMonths(tasks, cycle) {
    const dates = [
      parseISODate(cycle.planting_date),
      selectedDay,
      ...tasks.flatMap((t) => [parseISODate(t.scheduled_date), parseISODate(lastDay(t))]),
    ];
    const first = new Date(Math.min(...dates));
    const last = new Date(Math.max(...dates));
    const options = [];
    for (let d = new Date(first.getFullYear(), first.getMonth(), 1); d <= last; d.setMonth(d.getMonth() + 1)) {
      options.push(new Option(d.toLocaleDateString('en-PH', { month: 'long', year: 'numeric' }), toISODate(d).slice(0, 7)));
    }
    month.replaceChildren(...options);
    month.value = toISODate(selectedDay).slice(0, 7);
  }

  function dayTask(task, { ongoing = false } = {}) {
    const item = tpl('day-task').cloneNode(true);
    const check = item.querySelector('[data-check]');
    const time = ongoing ? `Until ${formatShortDate(parseISODate(lastDay(task)))}` : formatClock(hhmm(task.scheduled_time));
    item.querySelector('[data-time]').textContent = time || 'Any time';
    item.querySelector('[data-title]').textContent = task.title;
    item.classList.toggle('is-done', FINISHED.has(task.status));
    bindCheck(check, task, reload, view);
    return item;
  }

  function renderDays(tasks) {
    const day = toISODate(selectedDay);
    const starts = new Set(tasks.map((t) => t.scheduled_date));
    // The week strip follows the season's weeks, so it lines up with the timeline below.
    const sowing = calendar.cycle.planting_date;
    const first = weekStart(weekOf(day, sowing), sowing);
    const today = toISODate(philippineToday());
    const chips = [];
    for (let i = 0; i < 7; i += 1) {
      const date = addDays(first, i);
      const iso = toISODate(date);
      const chip = tpl('day').cloneNode(true);
      chip.querySelector('[data-dow]').textContent = date.toLocaleDateString('en-PH', { weekday: 'short' });
      chip.querySelector('[data-date]').textContent = String(date.getDate());
      chip.querySelector('[data-dot]').hidden = !starts.has(iso);
      chip.setAttribute('aria-pressed', String(iso === day));
      chip.setAttribute('aria-label', date.toLocaleDateString('en-PH', { weekday: 'long', month: 'long', day: 'numeric' }));
      chip.classList.toggle('is-today', iso === today);
      chip.addEventListener('click', () => {
        selectedDay = date;
        render();
      });
      chips.push(chip);
    }
    strip.replaceChildren(...chips);

    // A task with a range is listed on its start date; on its later days it shows under Ongoing.
    const startingToday = tasks.filter((t) => t.scheduled_date === day);
    const ongoing = tasks.filter((t) => t.scheduled_date < day && lastDay(t) >= day);
    dayList.replaceChildren(...startingToday.map((task) => dayTask(task)));
    ongoingList.replaceChildren(...ongoing.map((task) => dayTask(task, { ongoing: true })));
    ongoingTitle.hidden = ongoing.length === 0;
    dayEmpty.hidden = startingToday.length + ongoing.length > 0;
  }

  function checkRow(task) {
    const row = tpl('check').cloneNode(true);
    const check = row.querySelector('[data-check]');
    const tag = row.querySelector('[data-tag]');
    row.querySelector('[data-title]').textContent = task.title;
    row.classList.toggle('is-done', FINISHED.has(task.status));
    tag.hidden = task.status !== 'skipped';
    tag.textContent = 'Skipped';
    bindCheck(check, task, reload, view);
    return row;
  }

  function renderWeeks(tasks, cycle) {
    const sowing = cycle.planting_date;
    const groups = new Map();
    for (const task of tasks) {
      const no = weekOf(task.scheduled_date, sowing);
      if (!groups.has(no)) groups.set(no, []);
      groups.get(no).push(task);
    }
    const weeks = [...groups.keys()].sort((a, b) => a - b);
    const currentWeek = weekOf(toISODate(philippineToday()), sowing);
    const key = (no) => `${cycle.cycle_id}:${no}`;
    if (![...openWeeks].some((k) => k.startsWith(`${cycle.cycle_id}:`))) openWeeks.add(key(currentWeek));

    // By default show last week, this week and next week (or the nearest weeks with tasks).
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
      const start = weekStart(no, sowing);
      const card = tpl('week').cloneNode(true);
      const toggle = card.querySelector('[data-toggle]');
      const list = card.querySelector('[data-tasks]');
      const open = openWeeks.has(key(no));

      card.querySelector('[data-no]').textContent = weekLabel(no);
      card.querySelector('[data-stage]').textContent = labelOf(GROWTH_STAGES, items.find((t) => t.growth_stage)?.growth_stage);
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

  function render() {
    if (!calendar) return;
    content.hidden = false;
    renderSummary(calendar.cycle);
    renderMonths(calendar.items, calendar.cycle);
    renderDays(calendar.items);
    renderWeeks(calendar.items, calendar.cycle);
  }

  function renderPicker() {
    picker.replaceChildren(...fields.map(fieldOption));
    picker.value = shared.fieldId == null ? '' : String(shared.fieldId);
    picker.closest('.field-picker').hidden = fields.length === 0;
  }

  /** Loads the farm's fields and the chosen field's calendar. */
  async function reload({ keepFields = false } = {}) {
    const id = ++requestId;
    setStatus(view, '');
    try {
      if (!keepFields) {
        const loaded = await loadFirstFarm();
        if (id !== requestId) return;
        fields = loaded.farm ? loaded.fields : [];
      }
      view.querySelector('[data-empty]').hidden = true;
      syncFieldSelection(fields);
      renderPicker();
      if (!fields.length) {
        calendar = null;
        content.hidden = true;
        showEmpty(view, MESSAGES.noFarm, { setup: true });
        return;
      }
      const cycle = fields.find((f) => f.field_id === shared.fieldId)?.current_cycle;
      if (!cycle) {
        calendar = null;
        content.hidden = true;
        showEmpty(view, MESSAGES.noCycle);
        return;
      }
      const loaded = await api.forCycle(cycle.cycle_id);
      if (id !== requestId) return;
      calendar = loaded;
      render();
    } catch (err) {
      if (id !== requestId || isSessionEnd(err)) return;
      setStatus(view, errorMessage(err, MESSAGES.loadFailed), 'error');
    }
  }

  picker.addEventListener('change', () => {
    shared.fieldId = Number(picker.value);
    selectedDay = philippineToday();
    showAllWeeks = false;
    reload({ keepFields: true });
  });

  weekMore.addEventListener('click', () => {
    showAllWeeks = !showAllWeeks;
    render();
  });

  month.addEventListener('change', () => {
    const [year, mon] = month.value.split('-').map(Number);
    const first = calendar?.items.find((t) => t.scheduled_date.startsWith(month.value));
    selectedDay = first ? parseISODate(first.scheduled_date) : new Date(year, mon - 1, 1);
    render();
  });

  view.querySelector('[data-chat-soon]').addEventListener('click', (event) => {
    event.preventDefault();
    showToast(MESSAGES.chatbotSoon);
  });

  reloadWhenVisible(view, () => reload());

  return {
    enter() {
      selectedDay = philippineToday();
      reload();
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
  const tpl = (name) => view.querySelector(`template[data-${name}-tpl]`).content.firstElementChild;
  const filters = { query: '', fieldId: null, completed: false };
  let fields = [];
  let tasks = [];
  let loaded = false;
  let requestId = 0;

  /** field_id -> its current cycle, with the field name. */
  function cycleOf(task) {
    const field = fields.find((f) => f.current_cycle?.cycle_id === task.cycle_id);
    return field ? { ...field.current_cycle, field_name: field.field_name } : null;
  }

  function closeMenus(except) {
    view.querySelectorAll('[data-menu]').forEach((menu) => {
      if (menu === except) return;
      menu.hidden = true;
      menu.closest('.task-menu').querySelector('[data-menu-btn]').setAttribute('aria-expanded', 'false');
    });
  }

  function taskCard(task, { showField, overdue }) {
    const cycle = cycleOf(task);
    const card = tpl('task').cloneNode(true);
    const check = card.querySelector('[data-check]');
    const tag = card.querySelector('[data-tag]');
    const menuBtn = card.querySelector('[data-menu-btn]');
    const menu = card.querySelector('[data-menu]');
    const start = parseISODate(task.scheduled_date);
    const end = task.end_date ? parseISODate(task.end_date) : null;
    const week = cycle ? weekLabel(weekOf(task.scheduled_date, cycle.planting_date)) : null;
    const meta = [
      showField && cycle ? `${cycle.field_name} · ${cycle.crop_name}` : null,
      week,
      formatClock(hhmm(task.scheduled_time)),
      task.reminder ? 'Reminder on' : null,
    ];
    const details = [task.description, task.notes].filter(Boolean).join(' · ');

    card.querySelector('[data-title]').textContent = task.title;
    card.querySelector('[data-date]').textContent = (end ? formatRange(start, end) : formatShortDate(start)).toUpperCase();
    card.querySelector('[data-desc]').textContent = details;
    card.querySelector('[data-desc]').hidden = !details;
    card.querySelector('[data-meta]').textContent = meta.filter(Boolean).join(' · ');
    card.querySelector('[data-check-label]').textContent = `Mark "${task.title}" as done`;
    card.classList.toggle('is-done', FINISHED.has(task.status));
    bindCheck(check, task, reload, view);
    let label = '';
    if (overdue) label = 'Overdue';
    else if (task.status === 'skipped') label = 'Skipped';
    else if (task.status === 'rescheduled') label = 'Rescheduled';
    tag.hidden = !label;
    tag.textContent = label;
    tag.classList.toggle('status-tag--overdue', overdue);
    menuBtn.setAttribute('aria-label', `More actions for "${task.title}"`);

    const finished = FINISHED.has(task.status);
    card.querySelector('[data-action="done"]').hidden = task.status === 'done';
    card.querySelector('[data-action="undo"]').hidden = !finished;
    card.querySelector('[data-action="skip"]').hidden = finished;
    card.querySelector('[data-action="delete"]').hidden = !task.is_custom;

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

  async function change(task, payload, message) {
    setStatus(view, '');
    try {
      await api.update(task.activity_id, payload);
      showToast(message);
      await reload();
    } catch (err) {
      if (!isSessionEnd(err)) setStatus(view, errorMessage(err, MESSAGES.saveFailed), 'error');
    }
  }

  async function runAction(action, task) {
    if (action === 'done') await change(task, { status: 'done' }, MESSAGES.done);
    else if (action === 'undo') await change(task, { status: 'pending' }, MESSAGES.undone);
    else if (action === 'skip') await change(task, { status: 'skipped' }, MESSAGES.skipped);
    else if (action === 'reschedule') router.navigate('task-new', { state: { task, mode: 'reschedule' } });
    else if (action === 'edit') router.navigate('task-new', { state: { task, mode: 'edit' } });
    else if (action === 'delete' && window.confirm(MESSAGES.deleteConfirm(task.title))) {
      setStatus(view, '');
      try {
        await api.remove(task.activity_id);
        showToast(MESSAGES.deleted);
        await reload();
      } catch (err) {
        if (!isSessionEnd(err)) setStatus(view, errorMessage(err, MESSAGES.saveFailed), 'error');
      }
    }
  }

  /**
   * Groups of { title, week, entries: [{ task, overdue }] } in display order. Current Tasks
   * holds this season week's open tasks plus overdue ones (marked "Overdue"); Upcoming Tasks
   * follows by season week (per field when all plots are shown).
   */
  function groupTasks(list) {
    const byDate = (a, b) => a.scheduled_date.localeCompare(b.scheduled_date)
      || (hhmm(a.scheduled_time) || '~').localeCompare(hhmm(b.scheduled_time) || '~')
      || a.activity_id - b.activity_id;
    if (filters.completed) {
      const done = list.filter((t) => FINISHED.has(t.status)).sort((a, b) => byDate(b, a));
      return done.length ? [{ title: 'Completed Tasks', week: '', entries: done.map((task) => ({ task })) }] : [];
    }

    const today = toISODate(philippineToday());
    const allPlots = filters.fieldId == null;
    const current = [];
    const upcoming = new Map();
    for (const task of list.filter((t) => !FINISHED.has(t.status)).sort(byDate)) {
      const cycle = cycleOf(task);
      if (!cycle) continue;
      const thisWeek = weekOf(today, cycle.planting_date);
      const weekEnd = toISODate(addDays(weekStart(thisWeek, cycle.planting_date), 6));
      if (lastDay(task) < today) current.push({ task, overdue: true });
      else if (task.scheduled_date <= weekEnd) current.push({ task, overdue: false });
      else {
        const no = weekOf(task.scheduled_date, cycle.planting_date);
        const key = `${allPlots ? cycle.field_name : ''}|${no}`;
        if (!upcoming.has(key)) {
          const start = weekStart(no, cycle.planting_date);
          const range = formatRange(start, addDays(start, 6));
          upcoming.set(key, {
            start,
            week: `${allPlots ? `${cycle.field_name} · ` : ''}${weekLabel(no)} · ${range}`,
            entries: [],
          });
        }
        upcoming.get(key).entries.push({ task, overdue: false });
      }
    }

    const groups = [];
    if (current.length) {
      current.sort((a, b) => Number(b.overdue) - Number(a.overdue) || byDate(a.task, b.task));
      let week = '';
      if (!allPlots) {
        const cycle = fields.find((f) => f.field_id === filters.fieldId)?.current_cycle;
        if (cycle) {
          const no = weekOf(today, cycle.planting_date);
          const start = weekStart(no, cycle.planting_date);
          week = `${weekLabel(no)} · ${formatRange(start, addDays(start, 6))}`;
        }
      }
      groups.push({ title: 'Current Tasks', week, entries: current });
    }
    [...upcoming.values()]
      .sort((a, b) => a.start - b.start)
      .forEach((group, index) => groups.push({ ...group, title: index === 0 ? 'Upcoming Tasks' : '' }));
    return groups;
  }

  function render() {
    const empty = view.querySelector('[data-empty]');
    empty.hidden = true;
    const planted = fields.filter((field) => field.current_cycle);

    chipField.replaceChildren(new Option('Field', ''), ...planted.map(fieldOption));
    if (!planted.some((f) => f.field_id === filters.fieldId)) filters.fieldId = null;
    chipField.value = filters.fieldId == null ? '' : String(filters.fieldId);
    chipAll.setAttribute('aria-pressed', String(filters.fieldId == null));
    chipField.closest('.chip').classList.toggle('is-active', filters.fieldId != null);
    chipCompleted.setAttribute('aria-pressed', String(filters.completed));
    addTask.hidden = planted.length === 0;
    if (!loaded) return;

    if (!planted.length) {
      groupsEl.replaceChildren();
      showEmpty(view, fields.length ? MESSAGES.noCycle : MESSAGES.noFarm, { setup: !fields.length });
      return;
    }

    const query = filters.query.trim().toLowerCase();
    const fieldCycle = planted.find((f) => f.field_id === filters.fieldId)?.current_cycle;
    const list = tasks
      .filter((t) => !fieldCycle || t.cycle_id === fieldCycle.cycle_id)
      .filter((t) => !query || `${t.title} ${t.description ?? ''} ${t.notes ?? ''}`.toLowerCase().includes(query));

    const groups = groupTasks(list);
    groupsEl.replaceChildren(...groups.map((group) => {
      const el = tpl('group').cloneNode(true);
      const title = el.querySelector('[data-group-title]');
      const week = el.querySelector('[data-group-week]');
      title.textContent = group.title;
      title.hidden = !group.title;
      week.textContent = group.week;
      week.hidden = !group.week;
      el.querySelector('[data-group-list]').replaceChildren(
        ...group.entries.map(({ task, overdue }) => taskCard(task, { showField: filters.fieldId == null, overdue })),
      );
      return el;
    }));
    if (!groups.length) showEmpty(view, filters.completed ? MESSAGES.noCompleted : MESSAGES.noTasks);
  }

  /** The farm's fields and every task of their current cycles, page by page. */
  async function reload() {
    const id = ++requestId;
    setStatus(view, '');
    try {
      const { farm, fields: farmFields } = await loadFirstFarm();
      const all = [];
      if (farm) {
        for (let offset = 0; ; offset += PAGE_SIZE) {
          const page = await api.forFarm(farm.farm_id, { limit: PAGE_SIZE, offset });
          all.push(...page.items);
          if (page.items.length < PAGE_SIZE) break;
        }
      }
      if (id !== requestId) return;
      fields = farm ? farmFields : [];
      tasks = all;
      loaded = true;
      render();
    } catch (err) {
      if (id !== requestId || isSessionEnd(err)) return;
      setStatus(view, errorMessage(err, MESSAGES.loadFailed), 'error');
    }
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
  reloadWhenVisible(view, reload);

  return {
    enter({ from, state } = {}) {
      if (from === 'calendar') filters.fieldId = null;
      // After saving, show the saved task even if another field was filtered.
      if (state?.savedFieldId != null && filters.fieldId != null) filters.fieldId = state.savedFieldId;
      if (state?.savedFieldId != null) filters.completed = false;
      loaded = false;
      groupsEl.replaceChildren();
      render();
      reload();
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
  const subtitle = view.querySelector('[data-form-sub]');
  const saveButton = view.querySelector('[data-save-label]');
  const {
    title,
    field_id: fieldSelect,
    growth_stage: stage,
    scheduled_date: date,
    scheduled_time: time,
    reminder,
    notes,
  } = form.elements;
  let editing = null; // the task being edited or rescheduled
  let fields = [];
  let clientUuid = newClientUuid(); // kept for retries of the same new task

  for (const option of GROWTH_STAGES) stage.add(new Option(option.label, option.value));
  bindLiveErrorClearing(form);

  function cycleFor(fieldId) {
    return fields.find((f) => f.field_id === fieldId)?.current_cycle ?? null;
  }

  function validate() {
    const name = title.value.trim().replace(/\s+/g, ' ');
    if (!name) setFieldError(title, MESSAGES.titleRequired);
    if (!editing && !cycleFor(Number(fieldSelect.value))) setFieldError(fieldSelect, MESSAGES.fieldRequired);
    if (!parseISODate(date.value)) setFieldError(date, MESSAGES.dateRequired);
    if (form.querySelector('[aria-invalid="true"]')) return null;
    return {
      title: name,
      scheduled_date: date.value,
      scheduled_time: time.value || null,
      reminder: reminder.checked,
      notes: notes.value.trim() || null,
      growth_stage: stage.value || null,
    };
  }

  /** Only what changed; title and stage only on custom tasks. */
  function changes(values) {
    const patch = {};
    if (values.scheduled_date !== editing.scheduled_date) patch.scheduled_date = values.scheduled_date;
    if ((values.scheduled_time ?? '') !== hhmm(editing.scheduled_time)) patch.scheduled_time = values.scheduled_time;
    if (values.reminder !== editing.reminder) patch.reminder = values.reminder;
    if (values.notes !== (editing.notes ?? null)) patch.notes = values.notes;
    if (editing.is_custom) {
      if (values.title !== editing.title) patch.title = values.title;
      if (values.growth_stage !== (editing.growth_stage ?? null)) patch.growth_stage = values.growth_stage;
    }
    return patch;
  }

  function showError(err) {
    const code = err instanceof ApiError ? err.code : null;
    if (code === 'date_out_of_range') {
      setFieldError(date, MESSAGES[code]);
      focusFirstInvalid(form);
    } else {
      setStatus(view, errorMessage(err, MESSAGES.saveFailed), 'error');
    }
    if (code === 'client_uuid_taken') clientUuid = newClientUuid();
  }

  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    if (form.getAttribute('aria-busy') === 'true') return;
    clearFieldErrors(form);
    setStatus(view, '');
    const values = validate();
    if (!values) {
      focusFirstInvalid(form);
      return;
    }

    const fieldId = editing ? fields.find((f) => f.current_cycle?.cycle_id === editing.cycle_id)?.field_id : Number(fieldSelect.value);
    setBusy(form, true);
    try {
      if (editing) {
        const patch = changes(values);
        if (Object.keys(patch).length) await api.update(editing.activity_id, patch);
      } else {
        await api.create(cycleFor(fieldId).cycle_id, { ...values, client_uuid: clientUuid });
        clientUuid = newClientUuid();
      }
      if (fieldId != null) shared.fieldId = fieldId;
      showToast(MESSAGES.saved);
      router.navigate('tasks', { replace: true, state: { savedFieldId: shared.fieldId } });
    } catch (err) {
      if (!isSessionEnd(err)) showError(err);
    } finally {
      setBusy(form, false);
    }
  });

  view.querySelector('[data-cancel]').addEventListener('click', () => router.back('tasks'));

  function fill(task, mode) {
    editing = task;
    const generated = task && !task.is_custom;
    const titles = { reschedule: 'Reschedule Task', edit: 'Edit Farm Task' };
    heading.textContent = task ? titles[mode] ?? titles.edit : 'New Farm Task';
    subtitle.textContent = task ? 'Change the date, time, reminder, or notes.' : 'Schedule a new activity for your crop calendar.';
    saveButton.textContent = task ? 'Save Changes' : 'Save Task';
    title.disabled = Boolean(generated);
    stage.disabled = Boolean(generated);
    fieldSelect.disabled = Boolean(task);
    if (task) {
      const field = fields.find((f) => f.current_cycle?.cycle_id === task.cycle_id);
      title.value = task.title;
      fieldSelect.value = field ? String(field.field_id) : '';
      stage.value = task.growth_stage ?? '';
      date.value = task.scheduled_date;
      time.value = hhmm(task.scheduled_time);
      reminder.checked = task.reminder;
      notes.value = task.notes ?? '';
      if (mode === 'reschedule') requestAnimationFrame(() => date.focus());
    } else {
      fieldSelect.value = cycleFor(shared.fieldId) ? String(shared.fieldId) : '';
      date.value = toISODate(philippineToday());
      reminder.checked = false;
    }
  }

  router.route('task-new', {
    async onEnter({ state } = {}) {
      form.reset();
      clearFieldErrors(form);
      setStatus(view, '');
      const empty = view.querySelector('[data-empty]');
      empty.hidden = true;
      form.hidden = true;
      try {
        const loaded = await loadFirstFarm();
        fields = loaded.farm ? loaded.fields : [];
      } catch (err) {
        if (isSessionEnd(err)) return;
        showEmpty(view, MESSAGES.loadFailed);
        return;
      }
      const planted = fields.filter((f) => f.current_cycle);
      if (!planted.length) {
        showEmpty(view, MESSAGES.noTaskFields);
        return;
      }
      fieldSelect.replaceChildren(new Option('Select field', ''), ...planted.map(fieldOption));
      form.hidden = false;
      fill(state?.task ?? null, state?.mode);
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
