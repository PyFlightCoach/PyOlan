#!/usr/bin/env node
// Headless OpenAero trace harness for PyOlan's differential tests.
//
//   node oa-trace.js OA_ROOT --text 'seq text' ...
//   node oa-trace.js OA_ROOT --file seqs.txt          (one sequence per line)
//   node oa-trace.js OA_ROOT --library                (data/library.js, links expanded)
//   node oa-trace.js OA_ROOT --tables                 (OA.fig and OA.rollFig, with K)
//
// OA_ROOT is an OpenAero tree fetched by fetch_openaero.sh. Either layout loads:
// upstream's single js/main.js, or a js/main/*.js split (joined into one script).
//
// For each figure the trace records the aresti numbers, base, K (powered and
// glider), entry and exit direction and attitude, OpenAero's roll records, and the
// ordered geometric buildShape calls (Curve, Line, Roll, Snap, Spin, Hammer,
// Tailslide, Turn ...) with OA.attitude and OA.direction before and after each.
//
// Every sequence runs in Form B through checkSequenceChanged, which is the path
// taken when the text is typed in. Form B has no grid restarts (G) and no
// mirrored rolls (C, L). A library link may select another form, so it is loaded
// first, then its text is rebuilt in Form B. The rules worker is stubbed, so K
// is OpenAero's rule-free K (no kRules). The "non-Aresti rolls" setting is on,
// so every roll is drawn as written (a non-Aresti roll adds no K).
//
// The output is JSON on stdout. Change HARNESS_VERSION when the output changes.

const HARNESS_VERSION = "1";

const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { JSDOM, VirtualConsole } = require("jsdom");

const root = path.resolve(process.argv[2] || "");

function makeWindow() {
    const html = fs.readFileSync(path.join(root, "index.html"), "utf8");
    const srcs = [...html.matchAll(/<script src="([^"]+)"><\/script>/g)].map((m) => m[1]);
    const stripped = html.replace(/<script[\s\S]*?<\/script>/g, "");
    const errors = [];
    const virtualConsole = new VirtualConsole();
    virtualConsole.on("jsdomError", (e) => errors.push(String(e.message || e)));
    const dom = new JSDOM(stripped, { url: "http://localhost/", runScripts: "outside-only", pretendToBeVisual: true, virtualConsole });
    const w = dom.window;
    // the rules worker is not run: every check answers with no alerts
    w.Worker = class {
        constructor() { this.onmessage = null; }
        postMessage(m) {
            if (m && m.callbackId && this.onmessage) {
                setTimeout(() => {
                    try { this.onmessage({ data: { callbackId: m.callbackId, arguments: [{ alertMsgs: [], alertMsgRules: {} }] } }); }
                    catch (e) { errors.push("worker: " + e.message); }
                }, 0);
            }
        }
        terminate() {}
    };
    w.URL.createObjectURL = () => "blob:stub";
    w.matchMedia = w.matchMedia || (() => ({ matches: false, addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {} }));
    w.alert = () => {};
    Object.defineProperty(w.HTMLElement.prototype, "innerText", { get() { return this.textContent; }, set(v) { this.textContent = v; }, configurable: true });
    const p = w.SVGElement.prototype;
    p.createSVGPoint = () => ({ x: 0, y: 0, matrixTransform() { return { x: 0, y: 0 }; } });
    p.getBBox = () => ({ x: 0, y: 0, width: 0, height: 0 });
    p.getScreenCTM = () => ({ inverse() { return this; }, a: 1, b: 0, c: 0, d: 1, e: 0, f: 0 });
    p.getComputedTextLength = () => 0;
    w.HTMLCanvasElement.prototype.getContext = () => null;
    const ctx = dom.getInternalVMContext();
    const runScript = (code, name) => new vm.Script(code, { filename: name }).runInContext(ctx);
    const read = (f) => fs.readFileSync(f, "utf8").replace(/^﻿/, "");
    // upstream main.js also calls doOnLoad from a DOMContentLoaded listener;
    // initialise once, explicitly, below
    const addEL = w.document.addEventListener.bind(w.document);
    w.document.addEventListener = (type, ...rest) => (type === "DOMContentLoaded" ? undefined : addEL(type, ...rest));
    const mainDir = path.join(root, "js", "main");
    let mainDone = false;
    for (const src of srcs) {
        if (src.startsWith("js/main/")) {
            // split layout: the modules only work as one script
            if (mainDone) continue;
            mainDone = true;
            const files = fs.readdirSync(mainDir).filter((f) => f.endsWith(".js")).sort();
            runScript(files.map((f) => read(path.join(mainDir, f))).join("\n;\n"), "js/main/*.js");
        } else {
            runScript(read(path.join(root, src)), src);
        }
    }
    runScript("doOnLoad()", "doOnLoad");
    // "non-Aresti rolls" on: OpenAero then draws every roll as written. With it
    // off (OpenAero's default) a roll that is not in the Aresti catalogue, such as
    // a half spin, is silently drawn as a line, which is not the flight written.
    runScript("$('nonArestiRolls').checked = true;", "settings");
    runScript(`(() => {
        window.__cur = null; window.__traces = {};
        const GEOM = new Set(['Line','Curve','Corner','Roll','Snap','Spin','ShoulderRoll','Ruade','Lomcevak','Hammer','Tailslide','Turn','TurnRoll','PointTip','RollTopLine']);
        const origBF = buildFigure;
        buildFigure = function (figNrs, figString, seqNr, idx, chooser) {
            const outer = window.__cur;
            if (!chooser && idx >= 0) { window.__cur = idx; window.__traces[idx] = []; }
            try { return origBF.apply(this, arguments); } finally { window.__cur = outer; }
        };
        const origBS = buildShape;
        buildShape = function (name, params, paths) {
            if (window.__cur === null || !GEOM.has(name)) return origBS.apply(this, arguments);
            const rec = { shape: name, params: JSON.parse(JSON.stringify(params === undefined ? null : params)),
                att0: OA.attitude, dir0: OA.direction };
            const r = origBS.apply(this, arguments);
            rec.att1 = OA.attitude; rec.dir1 = OA.direction;
            window.__traces[window.__cur].push(rec);
            return r;
        };
    })()`, "wrap");
    return { dom, errors, exec: (c) => new vm.Script(c, { filename: "oa-trace" }).runInContext(ctx) };
}

const SNAP = `JSON.stringify({
    sequence_text: OA.sequenceText.innerText,
    rules: (typeof $ === 'function' && $('rules')) ? $('rules').value : null,
    category: (typeof $ === 'function' && $('category')) ? $('category').value : null,
    sportingClass: OA.sportingClass ? OA.sportingClass.value : null,
    figures: OA.figures.map((f, i) => ({
        index: i, string: f.string, aresti: f.aresti || null, base: f.base || null,
        k: f.k || null,
        entryDir: f.entryDir, entryAtt: f.entryAtt, exitDir: f.exitDir, exitAtt: f.exitAtt,
        entryAxis: f.entryAxis, exitAxis: f.exitAxis,
        rolls: f.rolls || null,
        trace: window.__traces[i] || null,
    })).filter((f) => f.aresti),
})`;

async function settle() { await new Promise((r) => setTimeout(r, 30)); }

function setClass(h, cls) {
    h.dom.window.__cls = cls;
    h.exec(`OA.sportingClass.value = window.__cls;`);
}

async function runText(h, text, cls) {
    h.dom.window.__text = text;
    if (cls) setClass(h, cls);
    h.exec(`(() => {
        window.__traces = {};
        alertBox = () => {}; confirmBox = () => {};
        OA.activeForm = 'B';
        OA.sequenceText.innerText = window.__text;
        OA.activeSequence.text = '';
        checkSequenceChanged(true);
    })()`);
    await settle();
    return JSON.parse(h.exec(SNAP));
}

// Run the text in the given class, then again in the other one for the other K.
async function runBothClasses(h, text, cls) {
    const first = await runText(h, text, cls);
    const other = first.sportingClass === "glider" ? "powered" : "glider";
    const second = await runText(h, first.sequence_text, other);
    setClass(h, first.sportingClass);
    const same = second.figures.length === first.figures.length &&
        second.figures.every((f, i) => f.string === first.figures[i].string);
    first.figures.forEach((f, i) => {
        const kOther = same ? second.figures[i].k : null;
        f.k_powered = first.sportingClass === "glider" ? kOther : f.k;
        f.k_glider = first.sportingClass === "glider" ? f.k : kOther;
        delete f.k;
    });
    if (!same) first.class_mismatch = true;
    return first;
}

async function runLink(h, url) {
    h.dom.window.__url = url;
    h.exec(`(() => { window.__traces = {}; alertBox = () => {}; confirmBox = () => {}; launchURL({ url: window.__url }); })()`);
    await settle();
    const first = JSON.parse(h.exec(SNAP));
    const linkForm = h.exec("OA.activeForm");
    // the link may select another form (e.g. grid); rebuild the text in Form B
    const again = await runBothClasses(h, first.sequence_text, first.sportingClass);
    return Object.assign(again, { rules: first.rules, category: first.category, sportingClass: first.sportingClass, link_form: linkForm });
}

function tables(h) {
    return JSON.parse(h.exec(`JSON.stringify({
        figures: OA.fig.filter((f) => f && f.pattern).map((f) => ({
            pattern: f.pattern, aresti: f.aresti, base: f.base || null,
            k_powered: f.kPwrd, k_glider: f.kGlider, draw: f.draw || null,
        })),
        rolls: Object.fromEntries(Object.entries(OA.rollFig).map(([key, r]) => [key, { aresti: r.aresti, k_powered: r.kPwrd, k_glider: r.kGlider }])),
    })`));
}

(async () => {
    const args = process.argv.slice(3);
    const h = makeWindow();
    const meta = { harness_version: HARNESS_VERSION, openaero_version: h.exec("typeof version !== 'undefined' ? String(version) : null") };
    let body;
    if (args[0] === "--tables") {
        body = tables(h);
    } else {
        const out = [];
        if (args[0] === "--library") {
            const src = fs.readFileSync(path.join(root, "data", "library.js"), "utf8").replace(/^﻿/, "");
            const lib = vm.runInNewContext(src + "\n;library");
            for (const [name, url] of Object.entries(lib)) {
                if (name === "version" || typeof url !== "string") continue;
                try { out.push(Object.assign({ name }, await runLink(h, url))); }
                catch (e) { out.push({ name, error: String(e.stack || e) }); }
            }
        } else {
            const inputs = args[0] === "--file"
                ? fs.readFileSync(args[1], "utf8").split("\n").filter((l) => l.trim())
                : args.slice(args[0] === "--text" ? 1 : 0);
            for (const s of inputs) {
                try { out.push(Object.assign({ input: s }, await runBothClasses(h, s, "powered"))); }
                catch (e) { out.push({ input: s, error: String(e.stack || e) }); }
            }
        }
        body = { sequences: out };
    }
    if (process.env.OA_DEBUG) console.error(h.errors.join("\n"));
    h.dom.window.close();
    // exit only once the output is flushed: a pipe is written asynchronously
    process.stdout.write(JSON.stringify(Object.assign(meta, body)), () => process.exit(0));
})().catch((e) => { console.error(e); process.exit(1); });
