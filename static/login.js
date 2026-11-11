(function () {
  var reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var cv = document.getElementById("waves");

  if (!cv) return;
  var ctx = cv.getContext("2d");
  var w = 0;
  var h = 0;

  var ribbons = [
    { y: 0.16, amp: 30, f: 0.0046, s: 0.55, p: 0.0, c: "255,204,0", a: 0.95, lw: 3.4, dash: null, chev: 2 },
    { y: 0.27, amp: 22, f: 0.0058, s: -0.42, p: 1.7, c: "255,255,255", a: 0.55, lw: 2, dash: [10, 12], chev: 0 },
    { y: 0.41, amp: 38, f: 0.0037, s: 0.38, p: 3.1, c: "212,5,17", a: 0.85, lw: 3.6, dash: null, chev: 1 },
    { y: 0.55, amp: 26, f: 0.0052, s: -0.6, p: 4.4, c: "255,204,0", a: 0.7, lw: 2.2, dash: [3, 11], chev: 0 },
    { y: 0.68, amp: 34, f: 0.0041, s: 0.5, p: 2.3, c: "255,255,255", a: 0.75, lw: 3, dash: null, chev: 2 },
    { y: 0.8, amp: 24, f: 0.0056, s: -0.35, p: 5.2, c: "255,204,0", a: 0.9, lw: 3, dash: null, chev: 1 },
    { y: 0.9, amp: 18, f: 0.0063, s: 0.45, p: 0.9, c: "105,36,19", a: 0.55, lw: 2.4, dash: [14, 10], chev: 0 }
  ];

  function size() {
    var dpr = Math.min(window.devicePixelRatio || 1, 1.5);
    w = cv.clientWidth;
    h = cv.clientHeight;
    cv.width = Math.round(w * dpr);
    cv.height = Math.round(h * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }

  function yAt(r, x, t) {
    return r.y * h + Math.sin(x * r.f + t * r.s + r.p) * r.amp + Math.sin(x * r.f * 2.3 - t * r.s * 0.7) * r.amp * 0.35;
  }

  function chevron(x, y, ang, col) {
    ctx.save();
    ctx.translate(x, y);
    ctx.rotate(ang);
    ctx.strokeStyle = col;
    ctx.lineWidth = 3.4;
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    ctx.beginPath();
    ctx.moveTo(-12, -8);
    ctx.lineTo(-3, 0);
    ctx.lineTo(-12, 8);
    ctx.moveTo(-2, -8);
    ctx.lineTo(7, 0);
    ctx.lineTo(-2, 8);
    ctx.stroke();
    ctx.restore();
  }

  function frame(now) {
    var t = now / 1000;
    ctx.clearRect(0, 0, w, h);
    for (var i = 0; i < ribbons.length; i++) {
      var r = ribbons[i];
      ctx.beginPath();
      for (var x = -10; x <= w + 10; x += 9) {
        var y = yAt(r, x, t);
        if (x === -10) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }
      ctx.strokeStyle = "rgba(" + r.c + "," + r.a + ")";
      ctx.lineWidth = r.lw;
      ctx.lineCap = "round";
      ctx.lineJoin = "round";
      ctx.setLineDash(r.dash || []);
      ctx.lineDashOffset = r.dash ? -t * 26 * (r.s > 0 ? 1 : -1) : 0;
      ctx.stroke();
      ctx.setLineDash([]);
      for (var c = 0; c < r.chev; c++) {
        var span = w + 160;
        var cx = ((t * 70 * (r.s > 0 ? 1 : -1) + (c * span) / r.chev + i * 190) % span + span) % span - 80;
        var cy = yAt(r, cx, t);
        var ang = Math.atan2(yAt(r, cx + 3, t) - yAt(r, cx - 3, t), 6);
        if (r.s < 0) ang += Math.PI;
        chevron(cx, cy, ang, "rgba(255,204,0,.98)");
      }
    }
    if (!reduce) requestAnimationFrame(frame);
  }

  size();
  window.addEventListener("resize", function () {
    size();
    if (reduce) frame(0);
  });

  if (reduce) {
    frame(0);
    return;
  }

  requestAnimationFrame(frame);
})();
