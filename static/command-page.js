import { api, toast, initShell } from "./common.js";
import { initCommandCenter } from "./command.js";

const { socket } = initShell();
initCommandCenter({ api, toast, socket });
