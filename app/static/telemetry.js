import {byId, clock, element} from "./views.js";

const LOG_LEVELS = {info: "采样", ok: "通过", warn: "复核", bad: "失败"};

export function startTelemetry(request) {
  const list = byId("log-stream");
  const button = byId("pause-log");
  const follow = byId("follow-state");
  const state = {paused: false, cursor: 0, revision: 0, online: true};

  function status() {
    follow.firstElementChild.className = `lamp ${state.paused ? "warn" : state.online ? "ok" : "bad"}`;
    follow.lastElementChild.textContent = state.paused ? "已暂停" : state.online ? "跟随中" : "日志重连中";
  }

  function append(events) {
    if (!events.length) return;
    byId("log-empty")?.remove();
    for (const event of events) {
      const node = element("li", "", "log-entry");
      node.dataset.sequence = event.seq;
      node.title = `${event.run_id} · ${event.code}`;
      const time = element("time", clock(event.time));
      time.dateTime = event.time;
      const level = element("span", "", `level level-${event.level}`);
      level.append(element("i", "", `lamp ${event.level}`), LOG_LEVELS[event.level] ?? event.level);
      const message = element("span", "", "log-message");
      if (event.source_time) message.append(element("span", clock(event.source_time), "source-time"));
      message.append(event.message);
      node.append(time, level, message);
      list.append(node);
    }
    while (list.childElementCount > 240) list.firstElementChild.remove();
    list.scrollTop = list.scrollHeight;
  }

  async function poll() {
    if (!state.paused) {
      const revision = state.revision;
      try {
        const payload = await request(`/api/batches/events?after=${state.cursor}&limit=8`);
        if (revision === state.revision && !state.paused) {
          append(payload.events);
          state.cursor = payload.cursor;
          if (state.cursor) byId("log-cursor").textContent = `序号 ${state.cursor}`;
        }
        state.online = true;
      } catch {
        state.online = false;
      }
      status();
    }
    window.setTimeout(poll, 650);
  }

  button.addEventListener("click", () => {
    state.paused = !state.paused;
    state.revision += 1;
    button.setAttribute("aria-pressed", String(state.paused));
    button.textContent = state.paused ? "继续滚动" : "暂停滚动";
    status();
  });
  status();
  poll();
}
