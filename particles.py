# fireworks
from random import uniform, gauss
import pyglet
from lepton import Particle, ParticleGroup, default_system, domain
from lepton.renderer import BillboardRenderer
from lepton.texturizer import SpriteTexturizer
from lepton.emitter import StaticEmitter, PerParticleEmitter
from lepton.controller import Lifetime, Movement, Fader, ColorBlender, Growth


class Trail:
    LIFETIME = 0.2

    sprite = pyglet.resource.texture('trail.png')
    group = ParticleGroup(
        controllers=[
            Lifetime(LIFETIME),
            #Fader(start_alpha=1.0, fade_out_start=0, fade_out_end=LIFETIME),
            Growth(-50),
            Movement(),
        ],
        renderer=BillboardRenderer(
            SpriteTexturizer(sprite.id)
        )
    )

    def __init__(self, player, viewport, level):
        self.player = player
        self.viewport = viewport
        self.level = level
        self.emitter = StaticEmitter(
            rate=player.body.velocity.length,
            template=Particle(
                position=(*level.map_to_world(player.position), 0),
                color=(1.0, 1.0, 1.0, 1.0),
                size=(16.0,) * 3,
            ),
        )
        self.group.bind_controller(self.emitter)
        pyglet.clock.schedule(self.update)

    def __del__(self):
        self.group.unbind_controller(self.emitter)

    def update(self, *_):
        level = self.level
        dir = self.player.body.velocity
        l = dir.length
        self.emitter.rate = l * 2

        if l:
            back = self.player.position - dir.normalized() * 0.1
            backwards = -0.1 * dir
            self.emitter.template.position = (*level.map_to_world(back), 0)
            self.emitter.template.velocity = (*level.map_to_world(backwards), 0)
            self.emitter.template.up = (0, 0, dir.get_angle() - self.viewport.angle)


class Kaboom:
    lifetime = 0.6

    color = (0.9, 0.6, 0.2, 0.3)

    spark_tex = pyglet.resource.texture('flare3.png')
    spark_texturizer = SpriteTexturizer(spark_tex.id)

    sparks = ParticleGroup(
        controllers=[
            Lifetime(lifetime),
            Movement(damping=0.93),
            ColorBlender([(0, (1,1,1,1)), (lifetime * 0.8, color), (lifetime, color)]),
            Fader(fade_out_start=0.3, fade_out_end=lifetime),
        ],
        renderer=BillboardRenderer(spark_texturizer)
    )

    trails = ParticleGroup(
        controllers=[
            Lifetime(lifetime * 1.5),
            Movement(damping=0.83),
            ColorBlender([(0, (1,1,1,1)), (1, color), (lifetime, color)]),
            Fader(max_alpha=0.75, fade_out_start=0, fade_out_end=lifetime),
        ],
        renderer=BillboardRenderer(spark_texturizer)
    )

    splosions = set()

    def __init__(self, position):
        x, y = position

        spark_emitter = StaticEmitter(
            template=Particle(
                position=(uniform(x - 5, x + 5), uniform(y - 5, y + 5), 0),
                size=(10,) * 3,
                color=self.color),
            deviation=Particle(
                velocity=(gauss(0, 5), gauss(0, 5), 0),
                age=1.5),
            velocity=domain.Sphere((0, gauss(40, 20), 0), 60, 60))

        spark_emitter.emit(int(gauss(60, 40)) + 50, self.sparks)

        spread = abs(gauss(0.4, 1.0))
        self.trail_emitter = PerParticleEmitter(self.sparks, rate=uniform(5,30),
            template=Particle(
                size=(6,) * 3,
                color=self.color),
            deviation=Particle(
                velocity=(spread, spread, spread),
                age=self.lifetime * 0.75))

        self.trails.bind_controller(self.trail_emitter)
        self.splosions.add(self)
        pyglet.clock.schedule_once(self.die, self.lifetime)

    def die(self, dt=None):
        self.trails.unbind_controller(self.trail_emitter)
        self.splosions.remove(self)
