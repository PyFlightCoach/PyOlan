#!/usr/bin/env node
// Export OpenAero's figure catalogue (data/figures/figures.js) for PyOlan's tests.
//
//   node export-figures.js OA_ROOT SHA HARNESS_VERSION OUT.json
//
// Ported from the catalogue exporter that lived in a local OpenAero branch
// (ad4dcf7, never pushed). The figures are read from the text of figures.js, so
// this does not run OpenAero. OA_ROOT must be the tree fetched at SHA.

const fs = require("node:fs");
const path = require("node:path");

const [root, sha, harnessVersion, outputPath] = process.argv.slice(2);
if (!outputPath) {
    console.error("usage: export-figures.js OA_ROOT SHA HARNESS_VERSION OUT.json");
    process.exit(2);
}
const source = fs.readFileSync(path.join(root, "data", "figures", "figures.js"), "utf8").replace(/^﻿/, "");
const entries = [];
const entryPattern = /^\s*"([^"\n]+)"\s*,?\s*$/gm;
const drawingAngles = {
    d: 45, v: 90, z: 135, m: 180, c: 225, p: 270, r: 315, o: 360,
    D: -45, V: -90, Z: -135, M: -180, C: -225, P: -270, R: -315, O: -360,
};
let match;
while ((match = entryPattern.exec(source)) !== null) {
    const metadata = match[1].match(/^(.+?)\s+([0-9]+\.[0-9.]+)\(([^)]*)\)\s+(.*)$/);
    if (!metadata) continue;
    const [, pattern, aresti, kFactors, drawing] = metadata;
    const [powered, glider] = kFactors.split(":").map((value) => {
        const number = Number(value);
        return Number.isFinite(number) ? number : null;
    });
    const renderPlan = [];
    let lineLength = 0;
    const flushLine = () => {
        if (lineLength > 0) {
            renderPlan.push({ kind: "line", length: lineLength });
            lineLength = 0;
        }
    };
    for (let index = 0; index < drawing.length; index += 1) {
        const character = drawing[index];
        if (character === "~") {
            lineLength += 1;
        } else if (character === "'") {
            lineLength += 0.5;
        } else if (Object.hasOwn(drawingAngles, character)) {
            flushLine();
            renderPlan.push({ kind: "arc", shape: character, angle: drawingAngles[character] });
        } else if (character === "j" || character === "J") {
            flushLine();
            let token = character;
            while (index + 1 < drawing.length && /[ioIO\d]/.test(drawing[index + 1])) {
                index += 1;
                token += drawing[index];
            }
            renderPlan.push({ kind: "turn", token });
        } else if (character === "_") {
            flushLine();
            renderPlan.push({ kind: "roll", marker: character });
        } else if (character === "4") {
            // the clover's fixed quarter roll (oj, mj, aj), drawn where it stands
            flushLine();
            renderPlan.push({ kind: "roll", marker: character });
        } else if (character === "!") {
            flushLine();
            renderPlan.push({ kind: "embedded_roll", marker: character });
        } else if ("hTtu".includes(character)) {
            flushLine();
            renderPlan.push({ kind: "special", shape: character });
        }
    }
    flushLine();
    entries.push({
        pattern,
        base_code: pattern.replace(/[+\-_^~&()]/g, "").replace(/^\$/g, ""),
        aresti,
        k_powered: powered,
        k_glider: glider ?? powered,
        drawing,
        semantics: {
            attitude: {
                entry: pattern.startsWith("-") ? "inverted" : "upright",
                exit: pattern.endsWith("-") ? "inverted" : "upright",
            },
            roll_slots: [...pattern.matchAll(/\(([^)]*)\)/g)].map((slot) => slot[1]),
            roll_markers: [...pattern].filter((c) => "_^&".includes(c)),
            drawing_operations: [...drawing].filter((c) => "~+/^'`._".includes(c)),
            drawing_shapes: [...drawing].filter((c) => "dDvVzZmMcCpPrRoOhHtTj".includes(c)),
            render_plan: renderPlan,
        },
    });
}
fs.writeFileSync(outputPath, `${JSON.stringify({
    source: {
        repository: "OpenAero/main",
        revision: sha,
        dirty: false,
        file: "data/figures/figures.js",
        harness_version: harnessVersion,
    },
    figures: entries,
}, null, 2)}\n`);
console.error(`Exported ${entries.length} figure definitions to ${outputPath}`);
