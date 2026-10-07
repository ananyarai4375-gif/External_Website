const movies = [
  {
    id: 1,
    title: "Nova Run",
    genre: "Action / Sci‑Fi",
    duration: "2h 14m",
    rating: "8.9",
    poster: "linear-gradient(135deg, #1a2a6c, #b21f66 48%, #fdbb2d)",
    showtimes: ["10:30 AM", "1:15 PM", "6:40 PM", "9:20 PM"]
  },
  {
    id: 2,
    title: "Aster's Light",
    genre: "Drama",
    duration: "1h 52m",
    rating: "8.6",
    poster: "linear-gradient(135deg, #113a44, #87bdb7 40%, #f7c59f)",
    showtimes: ["9:00 AM", "12:30 PM", "4:10 PM", "7:55 PM"]
  },
  {
    id: 3,
    title: "Black Harbor",
    genre: "Mystery / Thriller",
    duration: "2h 06m",
    rating: "8.4",
    poster: "linear-gradient(135deg, #181918, #334e68 40%, #9b5de5)",
    showtimes: ["11:45 AM", "2:25 PM", "8:00 PM"]
  },
  {
    id: 4,
    title: "Sunset Echo",
    genre: "Romance",
    duration: "1h 48m",
    rating: "8.1",
    poster: "linear-gradient(135deg, #7b2d26, #f77f00 35%, #f6bd60)",
    showtimes: ["10:15 AM", "1:00 PM", "5:30 PM", "9:45 PM"]
  }
];

const API_BASE_URL = (window.CINEVERSE_CONFIG?.API_BASE_URL || "").replace(/\/$/, "");
const API_PREFIX = `${API_BASE_URL}/api`;

const seatMap = Array.from({ length: 10 }, (_, rowIndex) =>
  Array.from({ length: 10 }, (_, seatIndex) => ({
    id: `${rowIndex + 1}-${seatIndex + 1}`,
    occupied: rowIndex === 0 || (rowIndex === 4 && seatIndex % 3 === 0) || (rowIndex === 7 && seatIndex > 5),
    selected: false
  }))
);

const state = {
  selectedMovie: movies[0],
  selectedShowtime: movies[0].showtimes[0],
  selectedSeats: new Set()
};

const movieGrid = document.querySelector("#movieGrid");
const bookingTitle = document.querySelector("#bookingTitle");
const showtimePill = document.querySelector("#showtimePill");
const seatMapElement = document.querySelector("#seatMap");
const totalPrice = document.querySelector("#totalPrice");
const toast = document.querySelector("#toast");
const bookButton = document.querySelector("#bookButton");
const busyScreen = document.querySelector("#busyScreen");
const busyRetry = document.querySelector("#busyRetry");
const busyStatus = document.querySelector("#busyStatus");
const theatreSelect = document.querySelector("#theatreSelect");
const dateSelect = document.querySelector("#dateSelect");
const sessionStorageKey = "cineverse-page-session";
const sessionId = sessionStorage.getItem(sessionStorageKey) || crypto.randomUUID();
let visitHeartbeat;
sessionStorage.setItem(sessionStorageKey, sessionId);

function sessionRequestOptions(body = {}) {
  return {
    method: "POST",
    cache: "no-store",
    headers: { "Content-Type": "application/json", "X-Session-ID": sessionId },
    body: JSON.stringify(body)
  };
}

function apiUrl(path) {
  return `${API_PREFIX}${path}`;
}

function renderMovies() {
  movieGrid.innerHTML = movies
    .map((movie) => {
      const isSelected = movie.id === state.selectedMovie.id;
      const showtimes = movie.showtimes
        .map((showtime) => `
          <button type="button" class="${showtime === state.selectedShowtime && isSelected ? "active" : ""}" data-movie-id="${movie.id}" data-showtime="${showtime}">
            ${showtime}
          </button>
        `)
        .join("");

      return `
        <article class="movie-card ${isSelected ? "selected" : ""}" data-movie-id="${movie.id}" tabindex="0">
          <div class="movie-poster" style="background: ${movie.poster};"></div>
          <h3>${movie.title}</h3>
          <div class="movie-meta">
            <span>${movie.genre}</span>
            <span>${movie.rating} ★</span>
          </div>
          <div class="movie-meta">
            <span>${movie.duration}</span>
            <span>Dolby Atmos</span>
          </div>
          <div class="movie-showtimes">${showtimes}</div>
        </article>
      `;
    })
    .join("");

  movieGrid.querySelectorAll(".movie-card").forEach((card) => {
    card.addEventListener("click", () => {
      const movieId = Number(card.dataset.movieId);
      const movie = movies.find((item) => item.id === movieId);
      state.selectedMovie = movie;
      state.selectedShowtime = movie.showtimes[0];
      state.selectedSeats.clear();
      renderMovies();
      renderBooking();
    });
  });

  movieGrid.querySelectorAll(".movie-showtimes button").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      const movieId = Number(button.dataset.movieId);
      const movie = movies.find((item) => item.id === movieId);
      state.selectedMovie = movie;
      state.selectedShowtime = button.dataset.showtime;
      state.selectedSeats.clear();
      renderMovies();
      renderBooking();
    });
  });
}

function renderBooking() {
  bookingTitle.textContent = `${state.selectedMovie.title} · ${state.selectedMovie.genre}`;
  showtimePill.textContent = state.selectedShowtime;
  totalPrice.textContent = `$${state.selectedSeats.size * 14}`;

  seatMapElement.innerHTML = "";
  seatMap.forEach((row, rowIndex) => {
    row.forEach((seat) => {
      const button = document.createElement("button");
      const isSelected = state.selectedSeats.has(seat.id);
      button.type = "button";
      button.className = `seat ${seat.occupied ? "occupied" : "available"} ${isSelected ? "selected" : ""}`;
      button.dataset.seatId = seat.id;
      button.setAttribute("aria-label", `${seat.occupied ? "Occupied" : "Available"} seat ${seat.id}`);
      button.disabled = seat.occupied;

      if (!seat.occupied) {
        button.addEventListener("click", () => toggleSeat(seat.id));
      }

      if (rowIndex === 0) {
        button.title = `Seat ${seat.id}`;
      }

      seatMapElement.appendChild(button);
    });
  });
}

function toggleSeat(seatId) {
  if (state.selectedSeats.has(seatId)) {
    state.selectedSeats.delete(seatId);
  } else {
    state.selectedSeats.add(seatId);
  }
  renderBooking();
}

function showToast(message) {
  toast.textContent = message;
  toast.classList.add("show");
  window.clearTimeout(showToast.timeoutId);
  showToast.timeoutId = window.setTimeout(() => toast.classList.remove("show"), 2200);
}

function setBusy(isBusy) {
  busyScreen.hidden = !isBusy;
  document.body.toggleAttribute("data-server-busy", isBusy);
}

async function registerVisit() {
  try {
    const response = await fetch(apiUrl("/visit"), { ...sessionRequestOptions(), signal: AbortSignal.timeout(8000) });
    const result = await response.json();
    setBusy(response.status === 503 || result.busy);
    if (!result.busy) busyStatus.textContent = "";
    window.clearInterval(visitHeartbeat);
    visitHeartbeat = window.setInterval(registerVisit, 10000);
  } catch (error) {
    console.error("Failed to register visitor", error);
    setBusy(true);
    busyStatus.textContent = "Could not reach the server. Check your connection and retry.";
    window.clearInterval(visitHeartbeat);
    visitHeartbeat = window.setInterval(registerVisit, 10000);
  }
}

async function submitBooking() {
  const response = await fetch(apiUrl("/booking"), sessionRequestOptions({
    movie: state.selectedMovie.title,
    theatre: theatreSelect.value,
    date: dateSelect.value,
    showtime: state.selectedShowtime,
    seats: [...state.selectedSeats]
  }));
  if (!response.ok) {
    throw new Error("Server busy");
  }
}

bookButton.addEventListener("click", async () => {
  if (state.selectedSeats.size === 0) {
    showToast("Select at least one seat");
    return;
  }

  try {
    await submitBooking();
    showToast(`Booked ${state.selectedSeats.size} ticket${state.selectedSeats.size > 1 ? "s" : ""} for ${state.selectedMovie.title}`);
    state.selectedSeats.clear();
    renderBooking();
  } catch (error) {
    if (error.message === "Server busy") {
      setBusy(true);
      busyStatus.textContent = "The booking service is at capacity. Retrying automatically…";
      return;
    }
    showToast("Server busy — please try again in a moment");
  }
});

window.addEventListener("beforeunload", () => {
  fetch(apiUrl("/leave"), { ...sessionRequestOptions({ sessionId }), keepalive: true }).catch(() => {});
});

busyRetry.addEventListener("click", () => {
  busyStatus.textContent = "Checking availability…";
  registerVisit();
});

registerVisit();
dateSelect.value = new Date().toISOString().slice(0, 10);
renderMovies();
renderBooking();
