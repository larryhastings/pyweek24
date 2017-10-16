import math
# pip3.6 install pyglet
import pyglet
import pyglet.resource
import pyglet.window.key
# pip3.6 install tmx
import tmx
# https://github.com/reidrac/pyglet-tiled-json-map.git
import json_map

key = pyglet.window.key

window = pyglet.window.Window()

pyglet.resource.path = [".", "gfx/kenney_roguelike/Spritesheet"]
pyglet.resource.reindex()


class Vector2D:
    def __init__(self, x, y=None):
        if y is None:
            assert isinstance(x, Vector2D)
            self.x = x.x
            self.y = x.y
            return

        self.x = x
        self.y = y

    def __repr__(self):
        return f"<{self.__class__.__name__} ({self.x}, {self.y})>"

    def __add__(self, other):
        if isinstance(other, Vector2D):
            return Vector2D(self.x + other.x, self.y + other.y)
        return Vector2D(self.x + other, self.y + other)

    def __sub__(self, other):
        if isinstance(other, Vector2D):
            return Vector2D(self.x - other.x, self.y - other.y)
        return Vector2D(self.x - other, self.y - other)

    def __mul__(self, other):
        if isinstance(other, Vector2D):
            return Vector2D(self.x * other.x, self.y * other.y)
        return Vector2D(self.x * other, self.y * other)

    # def __lt__(self, other):
    #     assert isinstance(other, Vector2D)
    #     return (self.x < other.x) or (self.y < other.y)

    # def __le__(self, other):
    #     assert isinstance(other, Vector2D)
    #     return (self.x <= other.x) and (self.y <= other.y)

    def __eq__(self, other):
        assert isinstance(other, Vector2D)
        return (self.x == other.x) and (self.y == other.y)

    # def __ge__(self, other):
    #     assert isinstance(other, Vector2D)
    #     return (self.x >= other.x) and (self.y >= other.y)

    # def __gt__(self, other):
    #     assert isinstance(other, Vector2D)
    #     return (self.x > other.x) and (self.y > other.y)

    def __ne__(self, other):
        assert isinstance(other, Vector2D)
        return (self.x != other.x) or (self.y != other.y)

    def __truediv__(self, other):
        if isinstance(other, Vector2D):
            return Vector2D(self.x / other.x, self.y / other.y)
        return Vector2D(self.x / other, self.y / other)

    def __bool__(self):
        return bool(self.x or self.y)

    def __getitem__(self, key):
        assert hasattr(key, '__index__')
        index = key.__index__()
        assert key in (0, 1)
        if key == 0:
            return self.x
        else:
            return self.y

    # TODO
    # this modifies self instead of returning a new object
    # inconsistent api here
    def clamp(self, other):
        if other.x == 0:
            self.x = 0
        elif other.x < 0:
            self.x = max(self.x, other.x)
        else:
            self.x = min(self.x, other.x)

        if other.y == 0:
            self.y = 0
        elif other.y < 0:
            self.y = max(self.y, other.y)
        else:
            self.y = min(self.y, other.y)




class Game:
    def __init__(self):
        self.paused = False

game = Game()

class Level:
    def __init__(self):
        fd = pyglet.resource.file("prototype.json")
        self.map = json_map.Map.load_json(fd)
        self.map.set_viewport(0, 0, window.width, window.height)

        self.tiles = tmx.TileMap.load("prototype.tmx")
        self.background_tiles, self.collision_tiles, self.player_position_tiles = (layer.tiles for layer in self.tiles.layers)
        self.upper_left = Vector2D(0, 0)
        self.lower_right = Vector2D(
            self.tiles.width * self.tiles.tilewidth,
            self.tiles.height * self.tiles.tileheight,
            )

        self.foreground_sprite_group = pyglet.graphics.OrderedGroup(self.map.last_group + 1)

    def draw(self):
        self.map.draw()

    def position_to_tile_index(self, x, y=None):
        if y is None:
            assert isinstance(x, Vector2D)
            y = x.y
            x = x.x
        index = int(((y // self.tiles.tileheight) * (self.tiles.width)) + 
            (x // self.tiles.tilewidth))
        assert index < len(self.collision_tiles)
        return index

    def tile_index_to_position(self, index):
        y = (index // self.tiles.width)
        x = index - (y * self.tiles.width) 
        y *= self.tiles.tileheight
        x *= self.tiles.tilewidth
        return Vector2D(x, y)

    def collision_tile_at(self, x, y=None):
        return self.collision_tiles[self.position_to_tile_index(x, y)].gid


level = Level()


sin_45degrees = math.sin(math.pi / 4)
vector_45degrees = Vector2D(sin_45degrees, sin_45degrees)


class Player:
    def __init__(self):
        # determine position based on first nonzero tile
        # found in player starting position layer
        for i, tile in enumerate(level.player_position_tiles):
            if tile.gid:
                # print("FOUND PLAYER TILE AT", i, level.tile_index_to_position(i))
                self.position = level.tile_index_to_position(i)
                break
        else:
            self.position = Vector2D(0, 0)
        # adjust player position
        # TODO why is this what we wanted?!
        self.position.y += level.tiles.tileheight 

        self.desired_speed = Vector2D(0, 0)
        self.normalized_desired_speed = Vector2D(0, 0)
        self.speed_multiplier = 10
        self.speed = Vector2D(0, 0)
        self.acceleration_frames = 20 # 20/60 of a second to get to full speed
        self.movement_keys = set()
        # coordinate system has (0, 0) at upper left
        self.movement_vectors = {
            key.UP:    Vector2D(0, -1),
            key.DOWN:  Vector2D(0, 1),
            key.LEFT:  Vector2D(-1, 0),
            key.RIGHT: Vector2D(1, 0),
            }
        self.movement_opposites = {
            key.UP: key.DOWN,
            key.DOWN: key.UP,
            key.LEFT: key.RIGHT,
            key.RIGHT: key.LEFT
            }

        self.image = pyglet.image.load("player.png")
        self.sprite = pyglet.sprite.Sprite(self.image, batch=level.map.batch, group=level.foreground_sprite_group)

    def calculate_normalized_desired_speed(self):
        if not (self.desired_speed.x and self.desired_speed.y):
            self.normalized_desired_speed = self.desired_speed
        else:
            self.normalized_desired_speed = self.desired_speed * vector_45degrees
        self.normalized_desired_speed *= self.speed_multiplier
        # print("normalized desired speed is now", self.normalized_desired_speed)

    def on_key_press(self, symbol, modifiers):
        if game.paused:
            return
        vector = self.movement_vectors.get(symbol)
        if vector:
            self.movement_keys.add(symbol)
            self.desired_speed += vector
            # if we press RIGHT while we're already pressing LEFT,
            # cancel out the LEFT (and ignore the keyup on it later)
            opposite = self.movement_opposites[symbol]
            if opposite in self.movement_keys:
                opposite_vector = self.movement_vectors[opposite]
                self.desired_speed -= opposite_vector
                self.movement_keys.remove(opposite)
            self.calculate_normalized_desired_speed()
            return pyglet.event.EVENT_HANDLED

    def on_key_release(self, symbol, modifiers):
        if game.paused:
            return
        if symbol in self.movement_keys:
            self.movement_keys.remove(symbol)
            vector = self.movement_vectors.get(symbol)
            self.desired_speed -= vector
            self.calculate_normalized_desired_speed()
            return pyglet.event.EVENT_HANDLED

    def on_player_move(self):
        self.sprite.x = self.position.x
        self.sprite.y = window.height - self.position.y - 1
        level.map.set_focus(self.position.x, self.position.y)

    def on_update(self, dt):
        # TODO
        # actually use dt here
        # instead of assuming it's 1/60 of a second
        # print("PLAYER UPDATE", self.speed, self.normalized_desired_speed)
        if self.speed != self.normalized_desired_speed:
            delta = self.normalized_desired_speed / self.acceleration_frames
            self.speed += delta
            self.speed.clamp(self.normalized_desired_speed)
            print("SPEED IS NOW", self.speed)
        if self.speed:
            new_position = self.position + self.speed
            if new_position.x < level.upper_left.x:
                new_position.x = level.upper_left.x
            if new_position.y < level.upper_left.y:
                new_position.y = level.upper_left.y
            if new_position.x > level.lower_right.x:
                new_position.x = level.lower_right.x
            if new_position.y > level.lower_right.y:
                new_position.y = level.lower_right.y
            # now check if we're colliding
            for key in self.movement_keys:
                vector = self.movement_vectors[key] * 8
                tile_position = new_position + vector
                if level.collision_tile_at(tile_position):
                    # throw away movement in bad direction
                    if vector.x:
                        new_position.x = self.position.x
                    else:
                        new_position.y = self.position.y
            # print("new position", new_position)
            if self.position != new_position:
                self.position = new_position
                # print("position now", self.position)
                self.on_player_move()

        def on_draw():
            pass


player = Player()
player.on_player_move()



keypress_handlers = {}
def keypress(key):
    def wrapper(fn):
        keypress_handlers[key] = fn
        return fn
    return wrapper


@keypress(key.ESCAPE)
def key_escape(pressed):
    print("ESC", pressed)
    pyglet.app.exit()

@keypress(key.SPACE)
def key_escape(pressed):
    print("SPACE", pressed)
    if pressed:
        game.paused = not game.paused

@keypress(key.UP)
def key_up(pressed):
    print("UP", pressed)

@keypress(key.DOWN)
def key_down(pressed):
    print("DOWN", pressed)

@keypress(key.LEFT)
def key_left(pressed):
    print("LEFT", pressed)

@keypress(key.RIGHT)
def key_right(pressed):
    print("RIGHT", pressed)


@keypress(key.LCTRL)
def key_lctrl(pressed):
    print("LEFT CONTROL", pressed)


@window.event
def on_key_press(symbol, modifiers):
    # ignoring modifiers for now
    handler = keypress_handlers.get(symbol)
    if handler:
        handler(True)
        return pyglet.event.EVENT_HANDLED

@window.event
def on_key_release(symbol, modifiers):
    # ignoring modifiers for now
    handler = keypress_handlers.get(symbol)
    if handler:
        handler(False)
        return pyglet.event.EVENT_HANDLED

window.push_handlers(player.on_key_press)
window.push_handlers(player.on_key_release)

@window.event
def on_draw():
    window.clear()
    level.draw()



def on_update(dt):
    player.on_update(dt)


pyglet.clock.schedule_interval(on_update, 1/60.0)

pyglet.app.run()