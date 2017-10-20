from contextlib import contextmanager
from math import floor, ceil, degrees

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
    attenuation = 200
    exponent = 2

    def __init__(self, position=(0, 0), color=(1.0, 1.0, 1.0)):
        self.position = position
        self.color = color


class LightRenderer:
    def __init__(self, viewport, shadow_casters=None, ambient=(0.15, 0.15, 0.3)):
        self.viewport = viewport
        self.shadow_casters = shadow_casters or {}
        self.lights = set()
        self.fbo = None
        self.ambient = ambient

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
        self.render()

    def render(self):
        """Render all lights."""
        gl.glEnable(gl.GL_TEXTURE_2D)
        gl.glActiveTexture(gl.GL_TEXTURE0)
        gl.glBindTexture(gl.GL_TEXTURE_2D, self.fbo.textures[0])
        lighting_shader.bind()
        lighting_shader.uniformi('diffuse_tex', 0)
#        lighting_shader.uniformf('viewport_pos', *self.viewport.pos)
#        lighting_shader.uniformf('viewport_dims', self.viewport.w, self.viewport.h)
#        lighting_shader.uniformf('viewport_angle', self.viewport.angle)
        gl.glEnable(gl.GL_BLEND)
        gl.glBlendFunc(gl.GL_ONE, gl.GL_ONE)
        for light in self.lights:
            self.render_light(light)
        lighting_shader.unbind()

        # Draw ambient using a full-screen quad
        gl.glColor3f(*self.ambient)
        self.viewport.draw_quad()
        gl.glColor4f(1, 1, 1, 1)
        gl.glBlendFunc(gl.GL_SRC_ALPHA, gl.GL_ONE_MINUS_SRC_ALPHA)

    def render_light(self, light):
        volumes = []
        x, y = light.position

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
                wall = self.shadow_casters.get((tx, ty), 0)
                if wall == 2:
                    vol = lightvolume.rect(
                        (tx + 0.25) * self.tilew, (tx + 0.75) * self.tilew,
                        (ty + 0.25) * self.tilew, (ty + 0.75) * self.tilew
                    )
                elif wall:
                    vol = lightvolume.rect(
                        tx * self.tilew, (tx + 1) * self.tilew,
                        ty * self.tilew, (ty + 1) * self.tilew
                    )
                else:
                    continue
                volumes.append(vol)

        wx = x * self.tilew
        wy = y * self.tilew
        lighting_shader.uniformf('light_pos', wx, wy)
        lighting_shader.uniformf('light_color', *light.color)
        lighting_shader.uniformf('attenuation', light.attenuation)
        lighting_shader.uniformf('exponent', light.exponent)
        lightvolume.draw_light((wx, wy), volumes)
