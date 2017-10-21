from contextlib import contextmanager
from math import floor, ceil, degrees, sqrt

from pyglet import gl
import lightvolume

from fbo import FrameBuffer
from shader import Shader


lighting_shader = Shader(
    vert="""
varying vec2 pos; // position of the fragment in screen space
varying vec2 uv;

uniform vec2 viewport_pos;
uniform vec2 viewport_dims;
uniform float viewport_angle;

void main(void)
{
    vec4 a = gl_Vertex;
    gl_Position = gl_ModelViewProjectionMatrix * a;
    pos = gl_Vertex.xy;
    uv = gl_Position.xy * 0.5 + vec2(0.5, 0.5);
}
""",
    frag="""
varying vec2 pos;
varying vec2 uv;

uniform vec2 light_pos;
uniform vec3 light_color;
uniform float attenuation;
uniform float exponent;
uniform sampler2D diffuse_tex;
uniform vec4 viewport;


void main (void) {
    //float l = viewport.x;
    //float r = viewport.y;
    //float b = viewport.z;
    //float t = viewport.w;
    //vec2 uv = vec2((pos.x - l) / (r - l), (pos.y - b) / (t - b));
    vec4 diffuse = texture2D(diffuse_tex, uv);

    //gl_FragColor = vec4(diffuse, 1.0);

    float dist = max(1.0 - distance(pos, light_pos) / attenuation, 0.0);
    float lum = pow(dist, exponent);
    gl_FragColor = lum * (diffuse * vec4(light_color, 1.0));
}
"""
)


class Light:
    exponent = 2

    def __init__(self, position=(0, 0), color=(1.0, 1.0, 1.0), radius=200):
        self.position = position
        self.color = color
        self.radius = radius


class LightRenderer:
    def __init__(self, viewport, shadow_casters=None, ambient=(0.15, 0.15, 0.3)):
        self.viewport = viewport
        self.shadow_casters = shadow_casters or {}
        self.lights = set()
        self.fbo = None
        self.ambient = ambient
        self.sh = None

    def _build_spatial_hash(self):
        sh = {}
        for (tx, ty), wall in self.shadow_casters.items():
            if wall:
                sh[tx, ty] = self._make_volume(tx, ty, wall)
        return sh

    def _make_volume(self, tx, ty, wall):
        if wall == 2:
            return lightvolume.rect(
                (tx + 0.25) * self.tilew, (tx + 0.75) * self.tilew,
                (ty + 0.25) * self.tilew, (ty + 0.75) * self.tilew
            )
        else:
            return lightvolume.rect(
                tx * self.tilew, (tx + 1) * self.tilew,
                ty * self.tilew, (ty + 1) * self.tilew
            )

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

        #self.vl.vertices = self.viewport_coords()

        with self.fbo:
            gl.glClear(gl.GL_COLOR_BUFFER_BIT | gl.GL_DEPTH_BUFFER_BIT)
            gl.glPushAttrib(gl.GL_ALL_ATTRIB_BITS)
            yield
            gl.glPopAttrib()

        if self.sh is None:
            self.sh = self._build_spatial_hash()
        self.render()

    def render(self):
        """Render all lights."""
        gl.glEnable(gl.GL_TEXTURE_2D)
        gl.glActiveTexture(gl.GL_TEXTURE0)
        gl.glBindTexture(gl.GL_TEXTURE_2D, self.fbo.textures[0])
        lighting_shader.bind()
        lighting_shader.uniformi('diffuse_tex', 0)
        gl.glEnable(gl.GL_BLEND)
        gl.glBlendFunc(gl.GL_ONE, gl.GL_ONE)

        vpw = self.viewport.w
        vph = self.viewport.h
        vpx, vpy = self.viewport.position
        vpradius = sqrt(vpw * vpw + vph * vph) * 0.5

        c = 0
        for light in self.lights:
            lx, ly = light.position
            maxdist = light.radius + vpradius
            dx = vpx - lx * self.tilew
            dy = vpy - ly * self.tilew
            dist = sqrt(dx * dx + dy * dy)
            if dist < maxdist:
                self.render_light(light)
                c += 1
        lighting_shader.unbind()

        # Draw ambient using a full-screen quad
        gl.glColor3f(*self.ambient)
        self.viewport.draw_quad()
        gl.glColor4f(1, 1, 1, 1)
        gl.glBlendFunc(gl.GL_SRC_ALPHA, gl.GL_ONE_MINUS_SRC_ALPHA)

    def render_light(self, light):
        volumes = []
        x, y = light.position

        tr = ceil(light.radius / self.tilew)
        l = x - tr
        r = x + tr
        b = y - tr
        t = y + tr

        volumes.append(
            lightvolume.rect(
                (l - 1) * self.tilew, (r + 1) * self.tilew,
                (b - 1) * self.tilew, (t + 1) * self.tilew,
            )
        )

        for tx in range(int(floor(l)), int(ceil(r))):
            for ty in range(int(floor(b)), int(ceil(t))):
                vol = self.sh.get((tx, ty))
                if vol:
                    volumes.append(vol)

        wx = x * self.tilew
        wy = y * self.tilew
        lighting_shader.uniformf('light_pos', wx, wy)
        lighting_shader.uniformf('light_color', *light.color)
        lighting_shader.uniformf('attenuation', light.radius)
        lighting_shader.uniformf('exponent', light.exponent)
        lightvolume.draw_light((wx, wy), volumes)
