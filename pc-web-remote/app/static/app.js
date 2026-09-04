const screen = document.getElementById("screen");
let socket = null;
let lastMove = 0;

function pos(event) {
  const rect = screen.getBoundingClientRect();
  const x = (event.clientX - rect.left) / Math.max(1, rect.width);
  const y = (event.clientY - rect.top) / Math.max(1, rect.height);
  return {
    x: Math.max(0, Math.min(1, x)),
    y: Math.max(0, Math.min(1, y)),
  };
}

function send(payload) {
  if (socket && socket.readyState === WebSocket.OPEN) {
    socket.send(JSON.stringify(payload));
  }
}

function connect() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  socket = new WebSocket(`${proto}://${location.host}/ws`);
  socket.binaryType = "blob";
  socket.onmessage = (event) => {
    if (typeof event.data === "string") {
      return;
    }
    const url = URL.createObjectURL(event.data);
    const old = screen.src;
    screen.src = url;
    if (old && old.startsWith("blob:")) {
      URL.revokeObjectURL(old);
    }
  };
  socket.onclose = () => {
    setTimeout(connect, 1000);
  };
}

screen.addEventListener("contextmenu", (event) => event.preventDefault());
screen.addEventListener("mousemove", (event) => {
  const now = performance.now();
  if (now - lastMove < 16) {
    return;
  }
  lastMove = now;
  const p = pos(event);
  send({ t: "move", x: p.x, y: p.y });
});
screen.addEventListener("mousedown", (event) => {
  event.preventDefault();
  const p = pos(event);
  send({ t: "down", x: p.x, y: p.y, b: event.button });
});
window.addEventListener("mouseup", (event) => {
  const p = pos(event);
  send({ t: "up", x: p.x, y: p.y, b: event.button });
});
screen.addEventListener("wheel", (event) => {
  event.preventDefault();
  send({ t: "wheel", d: Math.round(-event.deltaY) });
}, { passive: false });
window.addEventListener("keydown", (event) => {
  if (event.repeat) {
    return;
  }
  event.preventDefault();
  send({ t: "key", c: event.code, d: true });
});
window.addEventListener("keyup", (event) => {
  event.preventDefault();
  send({ t: "key", c: event.code, d: false });
});

connect();
