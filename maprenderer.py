import pyglet.graphics
import pyglet.sprite
from pyglet import gl
from shader import Shader

from json_map import get_texture_sequence


class Viewport:
    def __init__(self, w, h):
        self.w = w
        self.h = h
        self.pos = (0, 0)

    def bounds(self):
        """Return screen bounds as a tuple (l, r, b, t)."""
        w2 = self.w // 2
        h2 = self.h // 2
        x, y = self.pos
        return x - w2, x + w2, y - h2, y + h2

    def __enter__(self):
        gl.glPushMatrix()
        gl.glLoadIdentity()
        x, y = self.pos
        gl.glTranslatef(self.w // 2 - int(x), self.h // 2 - int(y), 0)

    def __exit__(self, *_):
        gl.glPopMatrix()


class MapRenderer:
    def __init__(self, tmxfile):
        self.light = 10, 10
        self.load(tmxfile)

    def load(self, tmxfile):
        """Populate a batch with sprites from the tmx file."""
        self.batch = pyglet.graphics.Batch()
        self.width = tmxfile.width
        self.height = tmxfile.height

        self.light_objects = []

        assert len(tmxfile.tilesets) == 1, "Multiple tilesets not supported."

        tileset = tmxfile.tilesets[0]
        filename = tileset.image.source
        self.tilew = tileset.tilewidth
        self.tileh = tileset.tileheight
        self.tiles_tex = get_texture_sequence(
            filename,
            self.tilew,
            self.tileh,
            tileset.margin,
            tileset.spacing
        )

        # Build mapping of tile texture by gid
        self.tiles = {}
        self.collision_gids = set()
        tileset.columns = 8  # FIXME: load from TMX
        rows = (tileset.tilecount + tileset.columns - 1) // tileset.columns
        tiles = iter(tileset.tiles)
        for y in range(rows):
            for x in range(tileset.columns):
                gid = x + y * tileset.columns + tileset.firstgid
                tex = self.tiles_tex[(rows - 1 - y), x]
                self.tiles[gid] = tex

                # Load which gids are collidable here
                tile = next(tiles, None)
                if tile:
                    props = {p.name: p.value for p in tile.properties}
                    if props.get('wall') == '1':
                        self.collision_gids.add(gid)

        self.sprites = {}
        for layernum, layer in enumerate(tmxfile.layers):
            for i, tile in enumerate(layer.tiles):
                if tile.gid == 0:
                    continue
                y, x = divmod(i, self.width)
                y = self.height - y - 1
                sprite = pyglet.sprite.Sprite(
                    self.tiles[tile.gid],
                    x=x * self.tilew,
                    y=y * self.tileh,
                    batch=self.batch,
                    usage="static"
                )
                self.sprites[x, y] = sprite

    def render(self):
        self.batch.draw()
