"""Support for render-to-texture."""
from pyglet import gl


COLOR_ATTACHMENTS = [
    gl.GL_COLOR_ATTACHMENT0,
    gl.GL_COLOR_ATTACHMENT1,
    gl.GL_COLOR_ATTACHMENT2,
    gl.GL_COLOR_ATTACHMENT3,
    gl.GL_COLOR_ATTACHMENT4,
    gl.GL_COLOR_ATTACHMENT5,
    gl.GL_COLOR_ATTACHMENT6,
    gl.GL_COLOR_ATTACHMENT7,
]


class FrameBuffer:
    """An interface to OpenGL Frame Buffer Objects.

    This implementation will generate a number of textures all of the same
    size, and attach them as colour buffers. Access the texture IDs of these
    textures from the 'textures' attribute (a sequence of texture IDs of length
    num_bufs).

    The depth buffer will be a render buffer, which is not readable.
    """
    fbo = None
    textures = ()
    depthbuf = None

    def __init__(self, width, height, num_bufs=1):
        assert 0 < num_bufs <= len(COLOR_ATTACHMENTS), \
            "Invalid number of buffers."
        self.width = width
        self.height = height
        self.num_bufs = num_bufs
        self._allocate()

    def _allocate(self):
        """Allocate the object."""
        def call(func, size):
            buf = (gl.GLuint * size)()
            func(size, buf)
            return list(buf)

        self.fbo = call(gl.glGenFramebuffers, 1)[0]
        self.textures = call(gl.glGenTextures, self.num_bufs)
        self.depthbuf = call(gl.glGenRenderbuffers, 1)[0]

        with self:
            self._link()

    def _link(self):
        for attachment, tex in zip(COLOR_ATTACHMENTS, self.textures):
            gl.glBindTexture(gl.GL_TEXTURE_2D, tex)
            gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_WRAP_S, gl.GL_REPEAT)
            gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_WRAP_T, gl.GL_REPEAT)
            gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MIN_FILTER, gl.GL_NEAREST)
            gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MAG_FILTER, gl.GL_NEAREST)
            gl.glTexImage2D(
                gl.GL_TEXTURE_2D, 0, gl.GL_RGBA32F,
                self.width, self.height,
                0,
                gl.GL_RGBA, gl.GL_FLOAT,
                None
            )

            gl.glFramebufferTexture2D(
                gl.GL_FRAMEBUFFER,
                attachment,
                gl.GL_TEXTURE_2D,
                tex,
                0
            )

        gl.glBindRenderbuffer(
            gl.GL_RENDERBUFFER,
            self.depthbuf
        )
        gl.glRenderbufferStorage(
            gl.GL_RENDERBUFFER,
            gl.GL_DEPTH_COMPONENT16,
            self.width,
            self.height
        )
        gl.glFramebufferRenderbuffer(
            gl.GL_FRAMEBUFFER,
            gl.GL_DEPTH_ATTACHMENT,
            gl.GL_RENDERBUFFER,
            self.depthbuf
        )

        assert gl.glCheckFramebufferStatus(gl.GL_FRAMEBUFFER) == gl.GL_FRAMEBUFFER_COMPLETE, \
            "Framebuffer is not complete!"

    def __del__(self):
        def call(func, vals):
            vals = list(vals)
            size = len(vals)
            buf = (gl.GLuint * size)(*vals)
            func(size, buf)

        if self.fbo:
            call(gl.glDeleteFramebuffers, [self.fbo])

        texids = filter(None, [self.depthbuf, *self.textures])
        if texids:
            call(gl.glDeleteTextures, texids)

    def __enter__(self):
        """Bind the FBO for rendering."""
        gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, self.fbo)

    def __exit__(self, *_):
        """Unbind the FBO."""
        gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, 0)
