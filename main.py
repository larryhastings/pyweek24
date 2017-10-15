# pip3.6 install pyglet
import pyglet
import pyglet.resource
# pip3.6 install tmx
import tmx
# https://github.com/reidrac/pyglet-tiled-json-map.git
import json_map


window = pyglet.window.Window()
label = pyglet.text.Label('Hello, world',
                      font_name='Times New Roman',
                      font_size=36,
                      x=window.width//2, y=window.height//2,
                      anchor_x='center', anchor_y='center')

# tiles = tmx.TileMap.load("prototype.tmx")
pyglet.resource.path = [".", "gfx/kenney_roguelike/Spritesheet"]
pyglet.resource.reindex()

# use pyglet's resource framework
fd = pyglet.resource.file("prototype.json")
m = json_map.Map.load_json(fd)
# set the viewport
m.set_viewport(0, 0, window.width, window.height)

@window.event
def on_draw():
    window.clear()
    m.draw()
    label.draw()

pyglet.app.run()