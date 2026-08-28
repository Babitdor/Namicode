import json

with open("/workspace/sfmcompileclub_posts.json") as f:
    data = json.load(f)

with open("/workspace/sfmcompileclub.html") as f:
    html = f.read()

old_js = """  const resp = await fetch('sfmcompileclub_posts.json');
  const data = await resp.json();
  let posts = data.posts || [];"""

new_js = f"  const POSTS_DATA = {json.dumps(data)};\n  let posts = POSTS_DATA.posts || [];"

html = html.replace(old_js, new_js)

with open("/workspace/sfmcompileclub.html", "w") as f:
    f.write(html)

print("Done — HTML size:", len(html), "bytes")