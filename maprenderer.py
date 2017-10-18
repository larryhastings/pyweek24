from math import floor, ceil
from contextlib import contextmanager

import pyglet.graphics
import pyglet.sprite
from pyglet import gl
from shader import Shader
import lightvolume

from json_map import get_texture_sequence
from fbo import FrameBuffer


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
        self.shadow_casters = {}  # quick spatial hash of shadow casting tiles
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
                tex.anchor_x = 0  # tex.width // 2
                tex.anchor_y = 0  # tex.height // 2
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
                if tile.gid in self.collision_gids:
                    self.shadow_casters[x, y] = True
                self.sprites[x, y] = sprite

    def render(self):
        self.batch.draw()


lighting_shader = Shader(
    vert="""
varying vec2 pos; // position of the fragment in screen space

void main(void)
{
    vec4 a = gl_Vertex;
    gl_Position = gl_ModelViewProjectionMatrix * a;
    pos = gl_Vertex.xy;
}
""",
    frag="""
varying vec2 pos;

uniform vec2 light_pos;
uniform vec3 light_color;
uniform float attenuation;
uniform float exponent;
uniform sampler2D diffuse_tex;
uniform vec4 viewport;


void main (void) {
    float l = viewport.x;
    float r = viewport.y;
    float b = viewport.z;
    float t = viewport.w;
    vec2 uv = vec2((pos.x - l) / (r - l), (pos.y - b) / (t - b));
    vec4 diffuse = texture2D(diffuse_tex, uv);

    //gl_FragColor = vec4(diffuse, 1.0);

    float dist = max(1.0 - distance(pos, light_pos) / attenuation, 0.0);
    float lum = pow(dist, exponent);
    gl_FragColor = lum * (diffuse * vec4(light_color, 1.0));
}
"""
)


class Light:
    attenuation = 300
    exponent = 2

    def __init__(self, pos=(0, 0), color=(1.0, 1.0, 1.0)):
        self.pos = pos
        self.color = color


class LightRenderer:
    def __init__(self, viewport, shadow_casters=None):
        self.viewport = viewport
        self.shadow_casters = shadow_casters or {}
        self.lights = set()
        self.fbo = None

    def add_light(self, light):
        """Add a light to the renderer."""
        self.lights.add(light)

    def remove_light(self, light):
        """Remove a light."""
        self.lights.discard(light)

    def is_fbo_valid(self):
        """Return True if the FBO still matches the size of the viewport."""
        return (
            self.fbo and
            self.fbo.width == self.viewport.w and
            self.fbo.height == self.viewport.h
        )

    @contextmanager
    def illuminate(self):
        if not self.is_fbo_valid():
            self.fbo = FrameBuffer(self.viewport.w, self.viewport.h)

        with self.fbo:
            gl.glClearColor(1.0, 1.0, 1.0, 1.0)
            gl.glClear(gl.GL_COLOR_BUFFER_BIT | gl.GL_DEPTH_BUFFER_BIT)
            gl.glPushAttrib(gl.GL_ALL_ATTRIB_BITS)
            yield
            gl.glPopAttrib()
        self.render()
        gl.glClearColor(0.0, 0.0, 0.0, 0.0)

    def render(self):
        """Render all lights."""
        lighting_shader.bind()
        gl.glEnable(gl.GL_TEXTURE_2D)
        gl.glActiveTexture(gl.GL_TEXTURE0)
        gl.glBindTexture(gl.GL_TEXTURE_2D, self.fbo.textures[0])
        lighting_shader.uniformi('diffuse_tex', 0)
        lighting_shader.uniformf('viewport', *self.viewport.bounds())
        gl.glEnable(gl.GL_BLEND)
        gl.glBlendFunc(gl.GL_SRC_ALPHA, gl.GL_ONE)
        for light in self.lights:
            self.render_light(light)
        gl.glBlendFunc(gl.GL_SRC_ALPHA, gl.GL_ONE_MINUS_SRC_ALPHA)
        lighting_shader.unbind()

    def render_light(self, light):
        volumes = []
        x, y = light.pos

        l = x - 6
        r = x + 6
        b = y - 6
        t = y + 6

        volumes.append(
            lightvolume.rect(
                (l - 1) * self.tilew, (r + 1) * self.tilew,
                (b - 1) * self.tilew, (t + 1) * self.tilew,
            )
        )

        for tx in range(int(floor(l)), int(ceil(r))):
            for ty in range(int(floor(b)), int(ceil(t))):
                if self.shadow_casters.get((tx, ty)):
                    volumes.append(
                        lightvolume.rect(
                            tx * self.tilew, (tx + 1) * self.tilew,
                            ty * self.tilew, (ty + 1) * self.tilew
                        )
                    )

        wx = x * self.tilew
        wy = y * self.tilew
        lighting_shader.uniformf('light_pos', wx, wy)
        lighting_shader.uniformf('light_color', *light.color)
        lighting_shader.uniformf('attenuation', light.attenuation)
        lighting_shader.uniformf('exponent', light.exponent)
        lightvolume.draw_light((wx, wy), volumes)
