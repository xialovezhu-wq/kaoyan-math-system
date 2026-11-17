/* Math-owned fixed examples. Payload contains only selected synthetic parameters. */
const CodexMathStudyRecipes = (() => {
  "use strict";
  const svgNS = "http://www.w3.org/2000/svg";
  const rad = Math.PI / 180;
  const svgNode = (kind, attributes, label) => {
    const node = document.createElementNS(svgNS, kind);
    for (const [key, value] of Object.entries(attributes)) node.setAttribute(key, value);
    if (label !== undefined) node.textContent = label;
    return node;
  };
  const el = (kind, label, css) => {
    const node = document.createElement(kind);
    if (label !== undefined) node.textContent = label;
    if (css) node.className = css;
    return node;
  };
  function button(label, change) {
    const node = el("button", label);
    node.type = "button";
    node.addEventListener("click", change);
    return node;
  }
  function choices(host, caption, id, entries, onSelect) {
    const group = el("fieldset");
    group.append(el("legend", caption));
    const inputs = entries.map(([value, label]) => {
      const control = el("input");
      control.type = "radio";
      control.name = id;
      control.value = value;
      control.addEventListener("change", () => { if (control.checked) onSelect(value); });
      const wrap = el("label");
      wrap.append(control, document.createTextNode(label));
      group.append(wrap);
      return control;
    });
    host.append(group);
    return value => inputs.forEach(control => { control.checked = control.value === value; });
  }
  function slider(host, label, min, max, change, step = 1) {
    const panel = el("label", label);
    const control = el("input");
    control.type = "range";
    control.min = min;
    control.max = max;
    control.step = step;
    control.addEventListener("input", () => change(Number(control.value)));
    panel.append(control);
    host.append(panel);
    return control;
  }
  function readout(host) {
    const row = el("p", "", "recipe-readout");
    row.setAttribute("aria-live", "polite");
    host.append(row);
    return row;
  }
  function plot(host, height, label) {
    const node = svgNode("svg", { viewBox: "0 0 600 " + height, role: "img",
      "aria-label": label, class: "recipe-plot" });
    host.append(node);
    return node;
  }
  function line(points, stroke, width, opacity = 1) {
    return svgNode("polyline", { points: points.map(q => q.join(",")).join(" "), fill: "none",
      stroke, "stroke-width": width, opacity, "stroke-linejoin": "round" });
  }
  const show = value => (Math.abs(value) < 1e-10 ? "0" : Number(value.toFixed(6)).toString()).replace("-", "−");
  function displaySlider(control, value, suffix = "") {
    control.value = value;
    control.setAttribute("aria-valuetext", show(value) + suffix);
  }
  function metrics(host, labels) {
    const list = el("dl", undefined, "recipe-metrics");
    const values = Object.entries(labels).map(([name, label]) => {
      const block = el("div"), number = el("dd");
      number.dataset.metric = name;
      block.append(el("dt", label), number);
      list.append(block);
      return [name, number];
    });
    host.append(list);
    return data => {
      for (const [name, number] of values) number.textContent = typeof data[name] === "number" ? show(data[name]) : data[name];
    };
  }
  function arrow(draw, from, to, ink, dashed = false) {
    const length = Math.hypot(to[0] - from[0], to[1] - from[1]);
    if (!length) return;
    const dx = (to[0] - from[0]) / length, dy = (to[1] - from[1]) / length;
    const shaft = line([from, to], ink, 2.5);
    if (dashed) shaft.setAttribute("stroke-dasharray", "5 4");
    const [x, y] = to, head = Math.min(12, length * .45), wing = head * .38;
    draw.push(shaft, svgNode("polygon", { points: [[x, y], [x - head * dx + wing * dy, y - head * dy - wing * dx],
      [x - head * dx - wing * dy, y - head * dy + wing * dx]].map(p => p.join(",")).join(" "), fill: ink }));
  }

  function drawRiemann(host, scene, id) {
    const { coefficients: [constant, quadratic], bounds: [low, high] } = scene.parameters;
    const f = x => constant + quadratic * x * x;
    const F = x => constant * x + quadratic * x * x * x / 3;
    const root = Math.sqrt(-constant / quadratic);
    let [a, b] = scene.parameters.interval, n = scene.parameters.n;
    const controls = el("div", undefined, "recipe-controls");
    const left = slider(controls, "起点 a", low, high, value => { a = value; render(); }, .1);
    const right = slider(controls, "终点 b", low, high, value => { b = value; render(); }, .1);
    const count = slider(controls, "分割数 n", 1, 128, value => { n = value; render(); });
    host.append(controls);
    const stats = metrics(host, { signedSum: "有符号近似和", integral: "精确定积分", area: "几何面积", error: "近似误差（绝对值）" });
    const direction = readout(host);
    const svg = plot(host, 347, "固定函数的曲线、中点矩形及当前积分方向");
    const legend = el("div", undefined, "recipe-sign-legend");
    legend.append(el("span", "+ 正贡献", "recipe-positive"), el("span", "− 负贡献（斜线）", "recipe-negative"));
    host.append(legend, el("p", "中点法 · 读数至多保留六位小数", "recipe-caption"));
    const X = x => 50 + 125 * (x - low), Y = y => 233 - 62 * y;
    const hatching = id + "-negative";
    const samples = Array.from({length: 161}, (_, i) => low + (high - low) * i / 160);
    function render() {
      const dx = (b - a) / n, lo = Math.min(a, b), hi = Math.max(a, b);
      const cuts = [lo, ...[-root, root].filter(x => x > lo && x < hi), hi];
      const area = cuts.slice(1).reduce((sum, end, i) => sum + Math.abs(F(end) - F(cuts[i])), 0);
      const integral = F(b) - F(a);
      const defs = svgNode("defs", {}), pattern = svgNode("pattern", {
        id: hatching, width: 8, height: 8, patternUnits: "userSpaceOnUse", patternTransform: "rotate(35)"
      });
      pattern.append(svgNode("rect", {width:8,height:8,fill:"var(--ink-b)","fill-opacity":.22}),
        svgNode("path", {d:"M0 0V8",stroke:"var(--ink-b)","stroke-width":2,"stroke-opacity":.78}));
      defs.append(pattern);
      const draw = [defs, line([[42, Y(0)], [565, Y(0)]], "var(--grid)", 1),
        line([[X(0), 39], [X(0), 299]], "var(--grid)", 1)];
      let signedSum = 0;
      if (dx !== 0) {
        for (let i = 0; i < n; i++) {
          const start = a + i * dx, value = f(start + dx / 2), term = value * dx;
          signedSum += term;
          const positive = term >= 0, ink = positive ? "var(--ink-a)" : "var(--ink-b)";
          draw.push(svgNode("rect", { x: X(Math.min(start, start + dx)), y: Y(Math.max(0, value)),
            width: Math.abs(125 * dx), height: Math.abs(Y(value) - Y(0)),
            fill: positive ? ink : "url(#" + hatching + ")", "fill-opacity": positive ? .24 : 1,
            stroke: ink, "stroke-width": 1, "data-contribution": term > 0 ? "positive" : term < 0 ? "negative" : "zero" }));
        }
        arrow(draw, [X(a), 323], [X(b), 323], "currentColor");
      }
      draw.push(line(samples.map(x => [X(x), Y(f(x))]), "currentColor", 2));
      for (const x of [-root, root]) {
        draw.push(svgNode("circle", {cx:X(x),cy:Y(0),r:3,fill:"currentColor"}),
          svgNode("text", {x:X(x),y:Y(0)+21,"text-anchor":"middle"}, show(x)));
      }
      draw.push(svgNode("text", {x:566,y:Y(0)+5}, "x"));
      svg.replaceChildren(...draw);
      const error = Math.abs(signedSum - integral);
      Object.assign(svg.dataset, { signedSum, integral, area, error, a, b, n });
      stats({ signedSum, integral, area, error });
      const note = "积分方向 " + show(a) + " → " + show(b) + " · n = " + n;
      if (direction.textContent !== note) direction.textContent = note;
      displaySlider(left, a); displaySlider(right, b); displaySlider(count, n, " 段");
    }
    render();
  }

  function drawGradient(host, scene) {
    const { coefficients: [height, xx, yy] } = scene.parameters;
    let [x, y] = scene.parameters.point, angle = scene.parameters.angle;
    const controls = el("div", undefined, "recipe-controls");
    const crossX = slider(controls, "点的 x", -2, 2, value => { x = value; render(); }, .05);
    const crossY = slider(controls, "点的 y", -2, 2, value => { y = value; render(); }, .05);
    const theta = slider(controls, "θ 相对 x 轴", 0, 360, value => { angle = value; render(); }, "any");
    host.append(controls);
    const presets = el("div", undefined, "recipe-buttons");
    const snaps = [["顺梯度", 0], ["反梯度", 180], ["垂直梯度", 90]].map(([label, offset]) => button(label, () => {
      const gx = 2 * xx * x, gy = 2 * yy * y;
      if (gx === 0 && gy === 0) return;
      angle = (Math.atan2(gy, gx) / rad + offset + 360) % 360;
      render();
    }));
    presets.append(...snaps);
    host.append(presets);
    const stats = metrics(host, { height: "高度", gradient: "梯度 ∇f", norm: "梯度模长", derivative: "方向导数" });
    const status = readout(host);
    const svg = plot(host, 365, "定义域 xy 平面上的解析椭圆等高线、梯度方向和单位方向");
    const legend = el("div", undefined, "recipe-sign-legend");
    legend.append(el("span", "∇f 梯度方向（实线）", "recipe-positive"), el("span", "u 单位方向（虚线）", "recipe-negative"));
    host.append(legend, el("p", "本例处处可微。换题先核可微、方向已单位化。", "recipe-caption"));
    const unit = 53, X = q => 300 + unit * q, Y = q => 183 - unit * q;
    function render() {
      const grad = [2 * xx * x, 2 * yy * y], norm = Math.hypot(...grad), u = [Math.cos(angle * rad), Math.sin(angle * rad)];
      const slope = grad[0] * u[0] + grad[1] * u[1], f = height + xx * x * x + yy * y * y;
      const draw = [line([[X(-3), Y(0)], [X(3), Y(0)]], "var(--grid)", 1),
        line([[X(0), 28], [X(0), 336]], "var(--grid)", 1)];
      for (const level of [2, 0, -3, -7]) {
        const rx = Math.sqrt((height - level) / -xx), ry = Math.sqrt((height - level) / -yy);
        draw.push(svgNode("ellipse", {cx:X(0),cy:Y(0),rx:unit*rx,ry:unit*ry,
          stroke:"var(--grid)",fill:"none","stroke-width":1.3}),
          svgNode("text", {x:X(rx)+6,y:Y(0)-6}, show(level)));
      }
      const p = [X(x), Y(y)];
      if (norm > 0) arrow(draw, p, [p[0] + 1.27 * unit * grad[0] / norm, p[1] - 1.27 * unit * grad[1] / norm], "var(--ink-a)");
      arrow(draw, p, [p[0] + unit * u[0], p[1] - unit * u[1]], "var(--ink-b)", true);
      draw.push(svgNode("circle", {cx:p[0],cy:p[1],r:4.8,fill:"currentColor"}),
        svgNode("text", {x:472,y:Y(0)+17}, "x"), svgNode("text", {x:X(0)+7,y:32}, "y"));
      svg.replaceChildren(...draw);
      Object.assign(svg.dataset, {x,y,angle,gradient:JSON.stringify(grad),height:f,norm,derivative:slope});
      stats({ height:f, gradient:"(" + grad.map(show).join(", ") + ")", norm, derivative:slope });
      snaps.forEach(control => { control.disabled = norm === 0; });
      const note = norm === 0 ? "梯度为零，相对梯度的方向未定义。θ 仍可调整。" : "点 (" + show(x) + ", " + show(y) + ") · θ = " + show(angle) + "°";
      if (status.textContent !== note) status.textContent = note;
      displaySlider(crossX, x); displaySlider(crossY, y); displaySlider(theta, angle, "°");
    }
    render();
  }
  function drawSaddle(host, scene, id) {
    const { coefficients: coef, half_span: span } = scene.parameters;
    const z = (x, y) => coef[0] * x * x + coef[1] * y * y;
    const h = 350, h0 = 174, unit = 70;
    let azimuth = 35, pitch = 32, section = "x0", active = null;
    const select = choices(host, "切换截线或切平面", id + "-section",
      [["x0", "x = 0"], ["y0", "y = 0"], ["tangent", "原点切平面"]], value => { section = value; render(); });
    const planeLabel = el("label", " 同时显示切平面");
    const plane = el("input");
    plane.type = "checkbox";
    planeLabel.prepend(plane);
    plane.addEventListener("change", render);
    const controls = el("div", undefined, "recipe-buttons");
    controls.append(planeLabel, button("重置视角", () => { azimuth = 35; pitch = 32; render(); }));
    const yaw = slider(controls, "水平视角", -180, 180, value => { azimuth = value; render(false); });
    const tilt = slider(controls, "俯仰视角", 8, 78, value => { pitch = value; render(false); });
    host.append(controls);
    const note = readout(host);
    const svg = plot(host, h, "按同一坐标系显示的鞍面和所选截面");
    const resolution = 18;
    const samples = Array.from({ length: resolution + 1 }, (_, i) => span * (2 * i / resolution - 1));
    const relations = {
      x0: "x = 0 截线：z = −y²。沿 y 方向向下弯。",
      y0: "y = 0 截线：z = x²。沿 x 方向向上弯。",
      tangent: "原点切平面：z = 0。因为 fₓ(0,0) = fᵧ(0,0) = 0。",
    };
    host.append(el("p", "同一曲面 z = x² − y²，观察点 (0, 0, 0)。曲面网格为绘图近似，截线和切平面公式为精确关系。",
      "recipe-caption"));
    function render(announce = true) {
      const c = Math.cos(azimuth * rad), s = Math.sin(azimuth * rad),
        cp = Math.cos(pitch * rad), sp = Math.sin(pitch * rad);
      function xy(x, y, height) {
        return [300 + unit * (c * x - s * y), h0 + unit * (sp * (s * x + c * y) - cp * height)];
      }
      const draw = [];
      if (section === "tangent" || plane.checked) {
        const q = span * .91;
        draw.push(svgNode("polygon", { points: [[-q,-q],[q,-q],[q,q],[-q,q]]
          .map(v => xy(...v, 0).join(",")).join(" "), fill: "var(--ink-b)", stroke: "var(--ink-b)",
          "fill-opacity": .10, "stroke-opacity": section === "tangent" ? .9 : .45 }));
      }
      for (const t of samples) {
        draw.push(line(samples.map(u => xy(t, u, z(t, u))), "var(--grid)", 1, .46));
        draw.push(line(samples.map(u => xy(u, t, z(u, t))), "var(--grid)", 1, .46));
      }
      const selected = (section === "x0" ? samples.map(u => [0, u]) :
        section === "y0" ? samples.map(u => [u,0]) : []);
      if (selected.length) draw.push(line(selected.map(v => xy(...v, z(...v))), "var(--ink-a)", 3));
      [[1.62,0,0,"x"],[0,1.62,0,"y"],[0,0,2.0,"z"]].forEach(([x,y,e,name]) => {
        const [a,b] = xy(x,y,e);
        draw.push(line([xy(0,0,0),[a,b]], "currentColor", 1, .45));
        draw.push(svgNode("text", {x:a+6,y:b+3},name));
      });
      draw.push(svgNode("circle", {cx:300,cy:h0,r:3.8,fill:"currentColor"}));
      svg.replaceChildren(...draw);
      svg.dataset.section = section;
      svg.dataset.tangent = String(section === "tangent" || plane.checked);
      select(section);
      yaw.value = azimuth;
      tilt.value = pitch;
      if (announce) note.textContent = relations[section];
    }
    svg.addEventListener("pointerdown", event => {
      active = [event.clientX, event.clientY, event.pointerId];
      svg.setPointerCapture(event.pointerId);
    });
    svg.addEventListener("pointermove", event => {
      if (!active || active[2] !== event.pointerId) return;
      azimuth = ((azimuth + event.clientX - active[0] + 540) % 360) - 180;
      pitch = Math.min(78, Math.max(8, pitch + event.clientY - active[1]));
      active = [event.clientX, event.clientY, event.pointerId];
      render(false);
    });
    for (const name of ["pointerup", "pointercancel", "lostpointercapture"]) svg.addEventListener(name, () => { active = null; });
    render();
  }
  function drawEigen(host, scene, id) {
    const matrices = scene.parameters.diagonals;
    const exactAxes = new Map([[0,[1,0]],[90,[0,1]],[180,[-1,0]],[270,[0,-1]]]);
    let mode = 0, angle = 0, invalid = false, active = null;
    const matrix = choices(host, "当前矩阵", id + "-matrix", [["0", "diag(2, −1)"], ["1", "diag(2, 0)"]], value => {
      mode = Number(value); if (mode === 1) angle = 90; invalid = false; render();
    });
    const controls = el("div", undefined, "recipe-buttons");
    for (const [label, degree] of [["沿 x 轴", 0], ["沿 y 轴", 90], ["斜方向", 45], ["反向 y 轴", 270]]) {
      controls.append(button(label, () => { angle = degree; invalid = false; render(); }));
    }
    controls.append(button("演示非法输入 u = 0", () => { invalid = true; render(); }),
      button("重置", () => { mode = 0; angle = 0; invalid = false; render(); }));
    const dial = slider(controls, "拖动方向角", 0, 359, value => { angle = value; invalid = false; render(); });
    host.append(controls);
    const note = readout(host);
    const svg = plot(host, 366, "同轴同尺度的输入向量与输出向量");
    const midX = 300, midY = 183, scale = 78, xy = ([x,y]) => [midX + x*scale, midY - y*scale];
    function drawArrow(vector, color, short, offset, dashed) {
      const p = xy(vector);
      const node = svgNode("g", { "data-vector": short });
      const norm = Math.hypot(...vector);
      if (!norm) {
        node.append(svgNode("circle", {cx:p[0],cy:p[1],r:5.5,fill:color,"data-zero":"true"}));
      } else {
        const points = [xy([0,0]), p];
        const l = line(points,color,3.3);
        if (dashed) l.setAttribute("stroke-dasharray","5 4");
        const [dx,dy] = [vector[0]/norm,-vector[1]/norm], [a,b] = p;
        node.append(l, svgNode("polygon", {points:[[a,b],[a-12*dx-5*dy,b-12*dy+5*dx],
          [a-12*dx+5*dy,b-12*dy-5*dx]].map(v => v.join(",")).join(" "),fill:color}));
      }
      node.append(svgNode("text", {x:p[0]+7,y:p[1]+offset}, norm ? short : short+" = 0"));
      return node;
    }
    const format = x => (Math.abs(x) < 1e-10 ? "0" : Number(x.toFixed(3)).toString()).replace("-", "−");
    const pair = v => "(" + v.map(format).join(", ") + ")";
    function render() {
      const axis = exactAxes.get(angle);
      const u = invalid ? [0,0] : axis || [Math.cos(angle*rad), Math.sin(angle*rad)];
      const d = matrices[mode], a = [d[0]*u[0], d[1]*u[1]];
      const squared = u[0]*u[0] + u[1]*u[1];
      const det = u[0]*a[1] - u[1]*a[0];
      const eigen = !invalid && Math.abs(det) <= 1e-12;
      const lambda = eigen ? (u[0]*a[0]+u[1]*a[1])/squared : null;
      const state = invalid ? "invalid" : !eigen ? "mixed" : lambda === 0 ? "zero" : lambda > 0 ? "positive" : "negative";
      matrix(String(mode));
      dial.value = angle;
      dial.setAttribute("aria-valuetext", angle + " 度");
      svg.dataset.state = state;
      svg.dataset.u = JSON.stringify(u);
      svg.dataset.au = JSON.stringify(a);
      svg.dataset.lambda = lambda === null ? "" : String(lambda);
      const draw = [line([xy([-3.4,0]),xy([3.4,0])],"var(--grid)",1),
        line([xy([0,-2.15]),xy([0,2.15])],"var(--grid)",1)];
      // Input and output share exactly the same scale. Dash distinguishes the input even when arrows overlap.
      draw.push(drawArrow(a,"var(--ink-b)","Au",-10,false), drawArrow(u,"var(--ink-a)","u",19,true));
      draw.push(svgNode("text",{x:570,y:176},"x"),svgNode("text",{x:307,y:20},"y"));
      svg.replaceChildren(...draw);
      const status = { positive: "同向，λ = 2。", negative: "反向，λ = −1。",
        zero: "Au = 0，输入 u 非零，满足 λ = 0。",
        invalid: "零输入示意。特征向量的输入必须非零。",
        mixed: "输入与输出不共线。"}[state];
      note.textContent = "A = diag(" + d.map(format).join(", ") + ")；u = " + pair(u) + "；Au = " + pair(a) + "。" + status;
    }
    function move(event) {
      const p = svg.createSVGPoint();
      p.x = event.clientX; p.y = event.clientY;
      const xyScreen = svg.getScreenCTM();
      if (!xyScreen) return;
      const q = p.matrixTransform(xyScreen.inverse());
      const x = q.x-midX, y = midY-q.y;
      if (Math.hypot(x,y) < 10) return;
      angle = (Math.round(Math.atan2(y,x)/rad)+360)%360;
      invalid = false;
      render();
    }
    svg.addEventListener("pointerdown", event => { active = event.pointerId; svg.setPointerCapture(active); move(event); });
    svg.addEventListener("pointermove", event => { if (event.pointerId === active) move(event); });
    for (const name of ["pointerup","pointercancel","lostpointercapture"]) svg.addEventListener(name, () => { active = null; });
    host.append(el("p", "判据是非零输入 u 存在标量 λ 使 Au = λu。精确轴向使用解析值，拖动小数为数值读数。", "recipe-caption"));
    render();
  }
  function drawDice(host, scene, id) {
    const faces = scene.parameters.faces, n = faces.length, square = n*n;
    let mode = "xy", row = 0, col = 0;
    const select = choices(host, "联合分布", id+"-dice",
      [["xy","X 和 Y：Y 与 X 是同一次结果"],["xz","X 和 Z：两次独立投掷"]], value => { mode = value; render(); });
    const note = readout(host);
    const table = el("table", undefined, "recipe-matrix");
    table.setAttribute("aria-label","联合概率表和边缘分布");
    const thead = el("thead"), head = el("tr"), name = el("th"), rows = el("tbody");
    head.append(name);
    for (const face of faces) head.append(el("th",String(face)));
    head.append(el("th","X 边缘"));
    thead.append(head);
    table.append(thead, rows);
    const cells = [];
    faces.forEach((i, r) => {
      const tr = el("tr");
      tr.append(el("th", String(i)));
      cells.push([]);
      faces.forEach((j,c) => {
        const td = el("td"), b = button("", () => {row=r;col=c;render();});
        b.dataset.cell = (r+1)+":"+(c+1);
        b.addEventListener("keydown", event => {
          const delta = {ArrowLeft:[0,-1],ArrowRight:[0,1],ArrowUp:[-1,0],ArrowDown:[1,0]}[event.key];
          if (!delta) return;
          event.preventDefault();
          row = Math.min(n-1,Math.max(0,r+delta[0]));
          col = Math.min(n-1,Math.max(0,c+delta[1]));
          render();
          cells[row][col].focus();
        });
        td.append(b); tr.append(td); cells[r].push(b);
      });
      tr.append(el("td","1/"+n,"recipe-marginal"));
      rows.append(tr);
    });
    const tail = el("tr"), edge = el("th");
    tail.append(edge, ...faces.map(() => el("td","1/"+n,"recipe-marginal")), el("td","1","recipe-marginal"));
    rows.append(tail);
    host.append(table,el("p","点选一格比较联合概率和边缘乘积。X、Y、Z 都是均匀边缘分布。判断独立需逐格核对。","recipe-caption"));
    function numerator(r,c) { return mode === "xz" ? 1 : r === c ? n : 0; }
    function readProb(num) { return num === 0 ? "0" : num === n ? "1/"+n : "1/"+square; }
    function render() {
      select(mode);
      const y = mode === "xz" ? "Z" : "Y";
      name.textContent = "X ∖ "+y; edge.textContent = y+" 边缘";
      const active = numerator(row,col);
      table.dataset.mode = mode; table.dataset.selected = (row+1)+":"+(col+1);
      table.dataset.sumNumerator = String(cells.reduce((t,a,r) => t + a.reduce((s,_,c) => s+numerator(r,c),0),0));
      cells.forEach((list,r) => list.forEach((b,c) => {
        const v = readProb(numerator(r,c));
        b.textContent = v;
        b.dataset.positive = String(numerator(r,c)>0);
        b.setAttribute("aria-pressed", String(r===row && c===col));
        b.setAttribute("aria-label", "X = "+faces[r]+"，"+y+" = "+faces[c]+"，联合概率 "+v);
        b.tabIndex = r === row && c === col ? 0 : -1;
      }));
      note.textContent = "P(X="+faces[row]+", "+y+"="+faces[col]+") = "+readProb(active)+
        "；边缘乘积 = 1/"+square+"。"+(mode === "xz" ? "所有格都相等，X 与 Z 独立。" :
        (active === 1 ? "此格相等。" : "此格不等，足以否定 X 与 Y 独立。"));
    }
    render();
  }
  function start(root, host, data) {
    const scene = data.scene;
    const panel = el("div", undefined, "math-recipe");
    panel.dataset.studyRecipe = scene.recipe_id;
    host.replaceChildren(panel);
    if (scene.recipe_id === "saddle-sections-tangent") drawSaddle(panel, scene, root.id);
    if (scene.recipe_id === "eigen-directions") drawEigen(panel, scene, root.id);
    if (scene.recipe_id === "same-distribution-vs-independence") drawDice(panel, scene, root.id);
    if (scene.recipe_id === "riemann-signed-area") drawRiemann(panel, scene, root.id);
    if (scene.recipe_id === "gradient-direction") drawGradient(panel, scene);
  }
  return {start};
})();
