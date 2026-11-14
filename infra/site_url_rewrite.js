// Maps a folder address to its index page, so /methods and /methods/ both serve
// methods/index.html (S5 spec §17.4). An address whose last part has a dot is a file and
// passes unchanged. Tested by tests/test_infra_site_stacks.py.
function handler(event) {
  var request = event.request;
  var uri = request.uri;
  if (uri.endsWith("/")) {
    request.uri = uri + "index.html";
  } else if (uri.split("/").pop().indexOf(".") === -1) {
    request.uri = uri + "/index.html";
  }
  return request;
}
