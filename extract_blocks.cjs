// Reads every block definition from a Music Blocks checkout and prints one JSON
// record per block. It runs the real js/protoblocks.js, so dockTypes, and with
// them the connection order in saved projects, come from Music Blocks itself.
//
// Usage: node extract_blocks.cjs <musicblocks checkout> > blocks.json

const fs = require("fs");
const path = require("path");

const checkout = process.argv[2];
if (!checkout) {
    console.error("usage: node extract_blocks.cjs <musicblocks checkout>");
    process.exit(2);
}
const jsDir = path.resolve(checkout, "js");

// A value that can be read, called or constructed as anything. Block
// constructors touch globals such as Singer or NOTENAMES that only matter when a
// block runs, never when it is defined.
function anything() {
    const target = function () {};
    return new Proxy(target, {
        get: (_, key) => (key === Symbol.toPrimitive ? () => "" : anything()),
        apply: () => anything(),
        construct: () => anything()
    });
}

global.createjs = { Container: anything(), Text: anything() };
global.DEFAULTBLOCKSCALE = 1.0;
global.STANDARDBLOCKHEIGHT = 20;
global._ = text => text;
global.last = list => list[list.length - 1];
global.localStorage = {};
global.navigator = { language: "en" };

const ProtoBlock = require(path.join(jsDir, "protoblocks.js"));
for (const name of [
    "BaseBlock",
    "ValueBlock",
    "BooleanBlock",
    "BooleanSensorBlock",
    "FlowBlock",
    "LeftBlock",
    "FlowClampBlock",
    "StackClampBlock"
]) {
    global[name] = ProtoBlock[name];
}

const blocks = [];
let currentFile = "";

// Record the palette name and the block instead of drawing anything.
ProtoBlock.BaseBlock.prototype.setPalette = function (palette) {
    this.paletteName = palette;
};
ProtoBlock.BaseBlock.prototype.setup = function () {
    blocks.push({ block: this, file: currentFile });
};

const activity = anything();

function baseClass(block) {
    let proto = Object.getPrototypeOf(block);
    while (proto && !Object.values(ProtoBlock).includes(proto.constructor)) {
        proto = Object.getPrototypeOf(proto);
    }
    return proto ? proto.constructor.name : "unknown";
}

const blockDir = path.join(jsDir, "blocks");
const files = fs
    .readdirSync(blockDir)
    .filter(name => name.endsWith(".js"))
    .sort();

for (const file of files) {
    currentFile = file;
    const modulePath = path.join(blockDir, file);
    // Undefined globals at load time get a stand-in, then the file loads again.
    for (let attempt = 0; ; attempt++) {
        const before = blocks.length;
        try {
            delete require.cache[require.resolve(modulePath)];
            const exported = require(modulePath);
            // Most files export { setupXBlocks }, a few export the function itself.
            const setups =
                typeof exported === "function"
                    ? [exported]
                    : Object.entries(exported)
                          .filter(([name, value]) => name.startsWith("setup") && typeof value === "function")
                          .map(([, value]) => value);
            if (setups.length === 0) throw new Error(`${file} exports no setup function`);
            for (const setup of setups) setup(activity);
            break;
        } catch (error) {
            blocks.length = before;
            const missing = /^(\w+) is not defined$/.exec(error.message);
            if (!missing || attempt > 50) throw error;
            global[missing[1]] = anything();
        }
    }
}

const records = blocks.map(({ block, file }) => {
    const style = block._style || {};
    const flows = style.flows || {};
    const help = Array.isArray(block.helpString) ? block.helpString[0] : "";
    return {
        name: block.name,
        label: (block.staticLabels && block.staticLabels[0]) || "",
        argLabels: style.argLabels || [],
        clampLabels: flows.labels || [],
        // "arg" means the clamp holds a growing list of arguments, not blocks.
        flowType: flows.type || null,
        palette: block.paletteName || "",
        file,
        base: baseClass(block),
        beginner: !!block.beginnerModeBlock,
        deprecated: !!block.deprecated,
        hidden: !!block.hidden,
        help: typeof help === "string" ? help : "",
        dockTypes: block.dockTypes || [],
        defaults: (block.defaults || []).filter(value => typeof value !== "function"),
        searchTerms: block.extraSearchTerms || []
    };
});

process.stdout.write(JSON.stringify(records, null, 1) + "\n");
console.error(`${records.length} blocks from ${files.length} files`);
