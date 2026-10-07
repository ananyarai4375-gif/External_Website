const apiBase = (window.CINEVERSE_CONFIG?.API_BASE_URL || "").replace(/\/$/, "");
const dashboardUrl = `${apiBase}/api/admin/dashboard`;
const elements = {
  activeUsers: document.querySelector("#activeUsers"),
  capacityLabel: document.querySelector("#capacityLabel"),
  vmCount: document.querySelector("#vmCount"),
  capacityValue: document.querySelector("#capacityValue"),
  lastEvent: document.querySelector("#lastEvent"),
  updatedAt: document.querySelector("#updatedAt"),
  vmGrid: document.querySelector("#vmGrid"),
  eventList: document.querySelector("#eventList"),
  healingBadge: document.querySelector("#healingBadge")
};

function renderDashboard(data) {
  elements.activeUsers.textContent = data.activeUsers;
  elements.capacityLabel.textContent = `${Math.max(data.capacity.current - data.activeUsers, 0)} slots available`;
  elements.vmCount.textContent = data.vmCount;
  elements.capacityValue.textContent = data.capacity.current;
  elements.lastEvent.textContent = data.lastEvent;
  elements.updatedAt.textContent = `Updated ${new Date(data.updatedAt * 1000).toLocaleTimeString()}`;
  elements.healingBadge.textContent = `● Self-healing ${data.selfHealing}`;
  elements.vmGrid.replaceChildren();
  for (const vm of data.vms) {
    const card = document.createElement("article");
    card.className = "vm-card";
    card.innerHTML = `<div class="vm-card-heading"><strong></strong><span class="vm-status"><i></i></span></div>
      <div class="usage-row"><span>CPU</span><strong></strong></div><div class="usage-track"><i></i></div>
      <div class="usage-row"><span>Memory</span><strong></strong></div><div class="usage-track memory-track"><i></i></div>`;
    card.querySelector(".vm-card-heading strong").textContent = vm.id;
    card.querySelector(".vm-status").append(document.createTextNode(vm.status));
    card.querySelectorAll(".usage-row strong")[0].textContent = `${vm.cpu}%`;
    card.querySelectorAll(".usage-track i")[0].style.width = `${vm.cpu}%`;
    card.querySelectorAll(".usage-row strong")[1].textContent = `${vm.memory}%`;
    card.querySelectorAll(".usage-track i")[1].style.width = `${vm.memory}%`;
    elements.vmGrid.append(card);
  }
  elements.eventList.replaceChildren();
  for (const event of data.scalingEvents) {
    const item = document.createElement("li");
    const dot = document.createElement("span");
    dot.className = `event-dot ${event.type === "scale-up" ? "scale-up" : ""}`;
    const content = document.createElement("div");
    const message = document.createElement("strong");
    message.textContent = event.message;
    const time = document.createElement("time");
    time.textContent = new Date(event.at * 1000).toLocaleTimeString();
    content.append(message, time);
    item.append(dot, content);
    elements.eventList.append(item);
  }
  if (!data.scalingEvents.length) elements.eventList.innerHTML = '<li class="empty-state">No scaling events yet. Events appear as the simulated capacity changes.</li>';
}

async function refreshDashboard() {
  try {
    const response = await fetch(dashboardUrl, { cache: "no-store" });
    if (!response.ok) throw new Error(`Dashboard request failed (${response.status})`);
    renderDashboard(await response.json());
  } catch (error) {
    elements.healingBadge.textContent = "● Backend unavailable";
    elements.healingBadge.classList.add("error-badge");
    elements.updatedAt.textContent = error.message;
  }
}

refreshDashboard();
window.setInterval(refreshDashboard, 3000);
