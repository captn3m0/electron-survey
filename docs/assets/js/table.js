// Progressive enhancement for the app listings: type-to-filter and
// click-to-sort. No dependencies; tables render fine with JS disabled.
(function () {
  "use strict";

  function cellValue(row, index) {
    var cell = row.cells[index];
    if (!cell) return "";
    var sort = cell.getAttribute("data-sort");
    return sort === null ? cell.textContent.trim() : sort;
  }

  function comparator(index, dir) {
    return function (a, b) {
      var x = cellValue(a, index);
      var y = cellValue(b, index);
      var nx = parseFloat(x);
      var ny = parseFloat(y);
      var same = !isNaN(nx) && !isNaN(ny);
      var cmp = same ? nx - ny : x.localeCompare(y, undefined, { numeric: true });
      return dir === "asc" ? cmp : -cmp;
    };
  }

  function enhance(table) {
    var body = table.tBodies[0];
    if (!body) return;
    var rows = Array.prototype.slice.call(body.rows);

    // Remember the server-rendered order so a third click can restore it.
    rows.forEach(function (row, i) { row.dataset.initialOrder = i; });

    var headers = Array.prototype.slice.call(table.tHead ? table.tHead.rows[0].cells : []);
    headers.forEach(function (th, index) {
      if (th.classList.contains("nosort")) return;
      th.classList.add("sortable");
      th.setAttribute("tabindex", "0");
      th.setAttribute("role", "button");

      function sort() {
        var dir = th.getAttribute("data-dir") === "asc" ? "desc"
          : th.getAttribute("data-dir") === "desc" ? "" : "asc";
        headers.forEach(function (other) { other.removeAttribute("data-dir"); });
        if (dir) {
          th.setAttribute("data-dir", dir);
          rows.sort(comparator(index, dir));
        } else {
          rows.sort(function (a, b) {
            return a.dataset.initialOrder - b.dataset.initialOrder;
          });
        }
        rows.forEach(function (row) { body.appendChild(row); });
      }

      th.addEventListener("click", sort);
      th.addEventListener("keydown", function (event) {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          sort();
        }
      });
    });

    var wrap = table.closest("[data-table]") || table.parentNode;
    var input = wrap.querySelector ? wrap.querySelector("input[type=search]") : null;
    var counter = wrap.querySelector ? wrap.querySelector(".count .shown") : null;
    if (!input) return;

    input.addEventListener("input", function () {
      var needle = input.value.trim().toLowerCase();
      var shown = 0;
      rows.forEach(function (row) {
        var hit = !needle || row.textContent.toLowerCase().indexOf(needle) !== -1;
        row.hidden = !hit;
        if (hit) shown++;
      });
      if (counter) counter.textContent = shown;
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    Array.prototype.forEach.call(document.querySelectorAll("table.data"), enhance);
  });
})();
