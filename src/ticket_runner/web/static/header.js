/* The thing behind the header.
 *
 * A raymarched gyroid tunnel, drawn in the bar the console opens with. No
 * library: three.js in this page would be six hundred kilobytes vendored — or a
 * CDN request, which is a console that stops looking like itself on a train —
 * to do what a full-screen quad and a fragment shader already do here in sixty
 * lines. WebGL is the standard library of the browser, the same way `http.server`
 * is the standard library of the server.
 *
 * It is not only decoration. The bar breathes with the runner: it flies faster
 * and turns warm while a ticket runs, ripples once for every event that lands on
 * the stream, and goes grey and red when the stream drops. You can tell from the
 * corner of your eye whether the machine is working.
 *
 * It gives the GPU back when nobody is looking — a hidden tab, a screen asking
 * for reduced motion, a context the driver took away — and quietly drops its own
 * resolution on a machine that cannot keep up. A pretty header that costs you a
 * fan spinning all afternoon is not a pretty header.
 */

(function () {
  "use strict";

  const VERTEX = `
    attribute vec2 position;
    void main() { gl_Position = vec4(position, 0.0, 1.0); }
  `;

  // GLSL ES 1.00 on purpose: a WebGL2 context accepts it too, so one shader
  // covers every browser that can draw at all.
  const FRAGMENT = `
    precision highp float;

    uniform vec2  uSize;
    uniform float uTime;
    uniform vec2  uMouse;    // -1..1 across the bar, for the parallax
    uniform float uEnergy;   // 0 idle, 1 a run in progress
    uniform float uPulse;    // 1 the instant an event lands, decaying to 0
    uniform float uAlive;    // 1 the stream is up, 0 it is not

    mat2 rot(float a) { float c = cos(a), s = sin(a); return mat2(c, -s, s, c); }

    // The console's own colours, walked along the ray: indigo to blue to violet
    // to pink while the runner waits, and the whole ramp swung into amber and
    // ember while it works. A cosine palette would be shorter and would fight
    // you every time you wanted one particular hue.
    vec3 palette(float x) {
      x = fract(x);
      vec3 cool = mix(vec3(0.16, 0.30, 0.88), vec3(0.40, 0.62, 1.00), smoothstep(0.00, 0.34, x));
      cool = mix(cool, vec3(0.70, 0.55, 1.00), smoothstep(0.30, 0.64, x));
      cool = mix(cool, vec3(1.00, 0.46, 0.75), smoothstep(0.60, 1.00, x));
      vec3 warm = mix(vec3(0.95, 0.24, 0.12), vec3(1.00, 0.74, 0.18), smoothstep(0.00, 0.55, x));
      warm = mix(warm, vec3(1.00, 0.36, 0.46), smoothstep(0.50, 1.00, x));
      return mix(cool, warm, uEnergy);
    }

    // A gyroid: an infinite surface with a one-line distance estimate. Three of
    // them at different scales, subtracted, is the whole lattice.
    float gyroid(vec3 p, float scale, float thickness, float bias) {
      p *= scale;
      return (abs(dot(sin(p), cos(p.zxy)) - bias) - thickness) / scale;
    }

    // How many lattice cells fit in a unit of the scene. Whatever it is, the
    // distance the march is handed has to come back out of that space, or every
    // step overshoots by the same factor and the picture dissolves into grain.
    const float CELLS = 3.0;

    float field(vec3 p) {
      p *= CELLS;
      p.xy *= rot(p.z * 0.16 + uTime * 0.07);
      float d = gyroid(p, 1.00, 0.030, 0.0);
      d -= gyroid(p, 3.30, 0.030, 0.30) * 0.34;
      d -= gyroid(p, 8.70, 0.030, 0.30) * 0.11;
      return d * 0.72 / CELLS;
    }

    void main() {
      // A fixed field of view up and down, and a widening one across, capped
      // before the rays at the ends turn sideways. Normalise by the height alone
      // and a bar this flat fans out into a smear; by the width alone and it
      // becomes a razor-thin slice through a scene it never gets to see.
      float aspect = uSize.x / max(uSize.y, 1.0);
      vec2 uv = (gl_FragCoord.xy / uSize - 0.5) * vec2(min(aspect, 3.2), 1.0) * 1.15;

      vec3 ro = vec3(0.0, 0.0, -2.2);
      vec3 rd = normalize(vec3(uv, 1.30));
      rd.yz *= rot(uMouse.y * 0.10);
      rd.xz *= rot(uMouse.x * 0.16);

      float speed = 0.26 + uEnergy * 0.60 + uPulse * 0.85;
      // Start each ray a hair's breadth apart from its neighbour. A march this
      // coarse would otherwise lay down visible rings; jittered, the error comes
      // out as fine noise, which is what the grain below is already made of.
      float t = fract(sin(dot(gl_FragCoord.xy, vec2(12.9898, 78.233))) * 43758.5453) * 0.055;

      // Density and depth, not colour. Summing a palette along a ray averages
      // every hue it passes into grey; summing a scalar and asking afterwards
      // where the light actually came from keeps the colour a colour.
      float glow = 0.0;
      float depth = 0.0;

      for (int i = 0; i < 64; i++) {
        vec3 p = ro + rd * t;
        p.z += uTime * speed;
        float d = abs(field(p));
        // A Lorentzian rather than 1/d: it falls away fast enough that the
        // lattice stays a lattice instead of blurring into weather.
        float w = exp(-t * 0.70) / (1.0 + d * d * 20000.0);
        glow += w;
        depth += w * t;
        t += max(d * 0.65, 0.045);
        if (t > 7.0) break;
      }
      depth /= max(glow, 1e-4);

      // Brightness out of the density, hue out of the palette, and the two kept
      // apart. Rolling the curve over all three channels — a per-channel tone
      // map, a gamma — is what turns a saturated dark blue into grey.
      float lum = max(glow * 0.34 - 0.05, 0.0);
      lum = pow(lum / (1.0 + lum), 0.80);
      vec3 col = palette(depth * 0.30 + uTime * 0.035) * lum;
      col = mix(col, vec3(1.0, 0.97, 0.94), pow(lum, 12.0) * 0.65);   // white-hot cores

      // The ripple: one bright sweep crossing the bar per event on the stream.
      float across = gl_FragCoord.x / uSize.x;
      col += palette(0.62) * exp(-abs(across - (1.0 - uPulse)) * 8.0) * uPulse * uPulse * 0.9;

      // A dropped stream drains the colour out and dims what is left. It has to
      // read as broken rather than as busy — ember is a colour the bar wears
      // when things are going well.
      float dead = 1.0 - uAlive;
      float grey = dot(col, vec3(0.299, 0.587, 0.114));
      col = mix(col, vec3(grey) * vec3(1.30, 0.52, 0.48), dead * 0.94) * (1.0 - dead * 0.30);

      col += (fract(sin(dot(gl_FragCoord.xy + uTime, vec2(12.9898, 78.233))) * 43758.5453) - 0.5) * 0.018;

      gl_FragColor = vec4(max(col, 0.0), 1.0);
    }
  `;

  function compile(gl, kind, source) {
    const shader = gl.createShader(kind);
    gl.shaderSource(shader, source);
    gl.compileShader(shader);
    if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) return null;
    return shader;
  }

  function start(canvas) {
    const options = { alpha: false, antialias: false, depth: false, powerPreference: "low-power" };
    const gl = canvas.getContext("webgl2", options) || canvas.getContext("webgl", options);
    if (!gl) return null;

    const vertex = compile(gl, gl.VERTEX_SHADER, VERTEX);
    const fragment = compile(gl, gl.FRAGMENT_SHADER, FRAGMENT);
    if (!vertex || !fragment) return null;

    const program = gl.createProgram();
    gl.attachShader(program, vertex);
    gl.attachShader(program, fragment);
    gl.linkProgram(program);
    if (!gl.getProgramParameter(program, gl.LINK_STATUS)) return null;
    gl.useProgram(program);

    gl.bindBuffer(gl.ARRAY_BUFFER, gl.createBuffer());
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);
    const position = gl.getAttribLocation(program, "position");
    gl.enableVertexAttribArray(position);
    gl.vertexAttribPointer(position, 2, gl.FLOAT, false, 0, 0);

    const at = (name) => gl.getUniformLocation(program, name);
    return { gl, uniforms: { size: at("uSize"), time: at("uTime"), mouse: at("uMouse"),
                             energy: at("uEnergy"), pulse: at("uPulse"), alive: at("uAlive") } };
  }

  const state = {
    energy: 0, energyTarget: 0,
    pulse: 0,
    alive: 1, aliveShown: 1,
    mouse: [0, 0], mouseTarget: [0, 0],
    hover: 0,
    time: 0,
    scale: Math.min(window.devicePixelRatio || 1, 1.25),
    slow: 0,
  };

  // Exported before anything is drawn, so app.js can talk to a header that
  // turned out to have no GPU behind it without checking first.
  const api = {
    setEnergy(value) { state.energyTarget = Math.max(0, Math.min(1, value)); },
    setAlive(alive) { state.alive = alive ? 1 : 0; },
    pulse() { state.pulse = 1; },
  };
  window.HeaderFX = api;

  function boot() {
    const canvas = document.getElementById("bar-fx");
    const bar = document.getElementById("bar");
    if (!canvas || !bar) return;

    const context = start(canvas);
    if (!context) { canvas.remove(); return; }   // the CSS underneath is a header on its own
    const { gl, uniforms } = context;
    bar.classList.add("fx");

    const still = window.matchMedia("(prefers-reduced-motion: reduce)");
    let width = 0;
    let height = 0;
    let last = 0;
    let frame = 0;
    let gone = false;   // the context was taken away and the canvas with it

    function measure() {
      if (gone) return;
      const box = bar.getBoundingClientRect();
      const w = Math.max(1, Math.round(box.width * state.scale));
      const h = Math.max(1, Math.round(box.height * state.scale));
      if (w === width && h === height) return;
      width = canvas.width = w;
      height = canvas.height = h;
      gl.viewport(0, 0, w, h);
    }

    function schedule() {
      // Asked for stillness: one frame, and then only when something changes.
      if (gone || still.matches) return;
      if (!frame) frame = requestAnimationFrame(draw);
    }

    // Under reduced motion the bar is a picture, redrawn when the runner's state
    // actually moves rather than sixty times a second.
    function redraw() { if (!gone && still.matches) requestAnimationFrame(draw); }

    function draw(now) {
      frame = 0;
      if (gone) return;
      const dt = last ? Math.min((now - last) / 1000, 0.1) : 0.016;
      last = now;

      // A header nobody is looking at is a header that costs nothing.
      if (document.hidden) { schedule(); return; }

      // A second of frames the machine could not keep up with, and it stops
      // asking so much of it.
      if (dt > 0.024) state.slow += 1; else state.slow = Math.max(0, state.slow - 1);
      if (state.slow > 60 && state.scale > 0.7) {
        state.scale = 0.7;
        state.slow = 0;
        width = height = 0;
        measure();
      }

      state.energy += (state.energyTarget - state.energy) * Math.min(1, dt * 2.2);
      state.aliveShown += (state.alive - state.aliveShown) * Math.min(1, dt * 3.0);
      state.pulse = Math.max(0, state.pulse - dt * 0.85);
      state.mouse[0] += (state.mouseTarget[0] - state.mouse[0]) * Math.min(1, dt * 4.0);
      state.mouse[1] += (state.mouseTarget[1] - state.mouse[1]) * Math.min(1, dt * 4.0);
      state.time += dt * (1 + state.hover * 0.6);

      gl.uniform2f(uniforms.size, width, height);
      gl.uniform1f(uniforms.time, state.time);
      gl.uniform2f(uniforms.mouse, state.mouse[0], state.mouse[1]);
      gl.uniform1f(uniforms.energy, state.energy);
      gl.uniform1f(uniforms.pulse, state.pulse);
      gl.uniform1f(uniforms.alive, state.aliveShown);
      gl.drawArrays(gl.TRIANGLES, 0, 3);

      schedule();
    }

    new ResizeObserver(() => { measure(); redraw(); }).observe(bar);
    measure();

    // The GPU can be taken away — a driver reset, a laptop coming back from
    // sleep. Rather than leave a black rectangle where the bar was, hand the
    // header back to the gradient underneath it.
    canvas.addEventListener("webglcontextlost", (event) => {
      event.preventDefault();
      gone = true;
      bar.classList.remove("fx");
      canvas.remove();
    });

    bar.addEventListener("pointermove", (event) => {
      const box = bar.getBoundingClientRect();
      state.mouseTarget = [
        ((event.clientX - box.left) / box.width) * 2 - 1,
        1 - ((event.clientY - box.top) / box.height) * 2,
      ];
      state.hover = 1;
    });
    bar.addEventListener("pointerleave", () => { state.mouseTarget = [0, 0]; state.hover = 0; });

    api.setEnergy = (value) => {
      state.energyTarget = Math.max(0, Math.min(1, value));
      if (still.matches) state.energy = state.energyTarget;
      redraw();
    };
    api.setAlive = (alive) => {
      state.alive = alive ? 1 : 0;
      if (still.matches) state.aliveShown = state.alive;
      redraw();
    };
    api.pulse = () => { if (!still.matches) state.pulse = 1; };

    document.addEventListener("visibilitychange", () => { if (!document.hidden) { last = 0; schedule(); } });
    still.addEventListener("change", () => { last = 0; schedule(); redraw(); });
    requestAnimationFrame(draw);
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
})();
