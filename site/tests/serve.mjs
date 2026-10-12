// Serves the built site as plain files for the accessibility check.
import { createServer } from "node:http";
import handler from "serve-handler";

createServer((request, response) => {
    if (request.url?.startsWith("/_holding/")) {
        request.url = request.url.slice("/_holding".length);
        return handler(request, response, { public: "holding" });
    }
    return handler(request, response, { public: "dist" });
}).listen(4321, "127.0.0.1");
