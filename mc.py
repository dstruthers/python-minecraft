import os, re, subprocess, sys, threading

SURVIVAL_MODE = 0
CREATIVE_MODE = 1
ADVENTURE_MODE = 2
SPECTATOR_MODE = 3

PEACEFUL = 0
EASY = 1
NORMAL = 2
HARD = 3

class MinecraftServer:
    """Wrap a Minecraft server and provide methods for interacting with it."""

    default_java_opts = '-Xmx2G -XX:MaxPermSize=128M -XX:+UseConcMarkSweepGC -XX:+UseParNewGC -XX:+AggressiveOpts'
    
    def __init__(self, minecraft_jar, directory=None, java='java', java_opts=default_java_opts):
        """Define Minecraft server."""
        self.jar_file = os.path.abspath(minecraft_jar)
        if directory is not None:
            self.directory = directory
        else:
            self.directory = os.getcwd()
        self.java = java
        self.java_opts = java_opts
        self.process = None
        self.start_handlers = []
        self.login_handlers = []
        self.logout_handlers = []
        self.death_handlers = []
        self.chat_handlers = []
        
    def read(self):
        """Read one line from server's stdout."""
        return self.process.stdout.readline()

    def send(self, data):
        """Send data to server's stdin."""
        self.process.stdin.write(data)

    def is_running(self):
        """Return True if server process is currently running."""
        self.process.poll()
        return self.process.returncode == None

    def start(self, daemon=False):
        """Start server process, optionally as a daemon."""
        args = [self.java, '-jar', self.jar_file]
        args.extend(self.java_opts.split())
        args.extend(['nogui'])

        os.chdir(self.directory)

        self.process = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

        for handler in self.start_handlers:
            handler()

        def listen_for_stdin():
            for line in iter(sys.stdin.readline, ''):
                self.send(line)

        listener = threading.Thread(target=listen_for_stdin)
        listener.daemon = True
        listener.start()

        try:
            for l in iter(self.process.stdout.readline, ''):
                self.process_server_output(l)
                print l,
        except KeyboardInterrupt:
            self.send('/stop')
            while self.process.poll() is None:
                try:
                    l = self.process.stdout.readline()
                    if l: print l,
                except IOError:
                    break

    def stop(self):
        """Stop server process."""
        self.send('/stop')

    def process_server_output(self, line):
        special_event_types = (LoginEvent, LogoutEvent, DeathEvent, ChatEvent)

        for event_type in special_event_types:
            try:
                event = event_type(line)
                break
            except LogParseError:
                continue
        else:
            event = ServerEvent(line)
            
        applicable_handlers = []
        if isinstance(event, LoginEvent):
            applicable_handlers.extend(self.login_handlers)
        elif isinstance(event, LogoutEvent):
            applicable_handlers.extend(self.logout_handlers)
        elif isinstance(event, DeathEvent):
            applicable_handlers.extend(self.death_handlers)
        elif isinstance(event, ChatEvent):
            for chat_handler in self.chat_handlers:
                if not re.match(chat_handler.pattern, event.chat):
                    continue
                if chat_handler.level is not None and event.level != chat_handler.level:
                    continue
                if chat_handler.thread is not None and event.thread != chat_handler.thread:
                    continue
                applicable_handlers.append(chat_handler.function)

        for handler in applicable_handlers:
            handler(event)

    def on_death(self, fn):
        self.death_handlers.append(fn)

    def on_login(self, fn):
        self.login_handlers.append(fn)

    def on_logout(self, fn):
        self.logout_handlers.append(fn)

    def on_start(self, fn):
        self.start_handlers.append(fn)

    def on_chat(self, pattern='^.*$', level=None, thread=None):
        def on_chat_decorator(function):
            self.chat_handlers.append(ChatHandler(pattern, level, thread, function))
        return on_chat_decorator

    # Game mode, difficulty, rules
    
    def set_difficulty(self, difficulty):
        """Set server difficulty level."""
        self.send('/difficulty %s\n' % difficulty)
        
    def set_game_mode(self, game_mode, player='@a'):
        """Set game mode, optionally for specific player."""
        self.send('/gamemode %s %s\n' % (game_mode, player))

    def set_default_game_mode(self, game_mode):
        """Set server's default game mode."""
        self.send('/defaultgamemode %s\n' % game_mode)
    
    def set_game_rule(self, rule, value):
        """Update game rule."""
        if isinstance(value, bool):
            value = str(value).lower()
            
        self.send('/gamerule %s %s\n' % (rule, value))

    # Time, weather
        
    def set_time(self, time):
        """Set in-game time."""
        self.send('/time set %s\n' % time)

    def toggle_downfall(self):
        """Toggle the weather."""
        self.send('/toggledownfall\n')

    def set_weather(self, weather, duration=''):
        """Set weather state."""
        self.send('/weather %s %s\n' % (weather, duration))

    # Effects, killing, XP

    def apply_effect(self, player, effect, duration=30, level=1):
        """Apply effect to player."""
        if abs(level) > 128:
            level = 128 if level > 0 else -128

        # convert integer value to that expected by /effect command
        if level < 0:
            level = 256 + level
        else:
            level -= 1

        self.send('/effect %s %s %s %s\n' % (player, effect, duration, level))

    def kill(self, player):
        """Kill player(s) and/or entities."""
        self.send('/kill %s\n' % player)

    def give_xp(self, player, amount):
        """Give XP to a player."""
        self.send('/xp %s %s\n' % (amount, player))
        
    # Server messages

    def say(self, message):
        """Send server message to players."""
        self.send('/say %s\n' % message)

    def tell(self, player, message):
        """Send private message to one or more players."""
        self.send('/tell %s %s\n' % (player, message))
        
    def tell_raw(self, player, message):
        """Send private raw (JSON) message to one or more players."""
        self.send('/tellraw %s %s\n' % (player, message))

    # Achievements

    def give_achievement(self, achievement, player):
        """Give achievement to player(s)."""
        self.send('/achievement give %s %s\n' % (achievement, player))

    def take_achievement(self, achievement, player):
        """Take achievement from player(s)."""
        self.send('/achievement take %s %s\n' % (achievement, player))

    # White list, ban list, permissions

    def make_op(self, player):
        """Promote player to op."""
        self.send('/op %s\n' % player)

    def deop(self, player):
        """Demote player from op."""
        self.send('/deop %s\n' % player)
    
    def ban_player(self, player, reason=''):
        """Ban player from server."""
        self.send('/ban %s %s\n' % (player, reason))

    def ban_ip(self, ip, reason=''):
        """Ban connections from IP address."""
        self.send('/ban-ip %s %s\n' % (ip, reason))

    def pardon_player(self, player):
        """Remove player from the ban list."""
        self.send('/pardon %s\n' % player)

    def pardon_ip(self, ip):
        """Remove IP address from the ban list."""
        self.send('/pardon-ip %s\n' % ip)

    def kick_player(self, player, reason=''):
        """Forcibly remove player from server."""
        self.send('/kick %s %s\n' % (player, reason))

    def set_idle_timeout(self, minutes):
        """Sets the time before idle players are kicked from the server."""
        self.send('/setidletimeout %s\n' % minutes)

    # Inventory management

    def give_item(self, player, item, amount=1, data=None, data_tag=None):
        """Give item(s) to player."""
        command = '/give %s %s %s' % (player, item, amount)
        if data:
            command += ' ' + data
        if data_tag:
            command += ' ' + data_tag

        self.send(command + '\n')
    
    def clear_inventory(self, player, item=None, data=None, max_count=None, data_tag=None):
        """Remove item(s) from a player's inventory."""
        command = '/clear ' + player
        if item:
            command += ' ' + item
            if data:
                command += ' ' + data
        if max_count:
            command += ' ' + max_count
        if data_tag:
            command += ' ' + data_tag

        self.send(command + '\n')

    # Sounds, particles

    def play_sound(self, sound, source, player, x='~', y='~', z='~', volume=1, pitch=1, min_volume=0):
        """Play sound."""
        self.send('/playsound %s %s %s %s %s %s %s %s %s\n' % (sound, source, player, x, y, z, volume, pitch, min_volume))

    def stop_sound(self, player, source='master', sound=None):
        """Stop a sound from playing."""
        command = '/stopsound %s %s' % (player, source)
        if sound:
            command += ' ' + sound
        self.send(command + '\n')

    def particle_effect(self, name, x, y, z, xd, yd, zd, speed, count=0, mode='', player=None, params=None):
        """Display particle effects."""
        command = '/particle %s %s %s %s %s %s %s %s %s' % (name, x, y, z, xd, yd, zd, speed, count)
        if player:
            command += ' ' + player
        if params:
            command += ' ' + params
        self.send(command + '\n')

    # Saving

    def save_all(self, flush=False):
        """Save server state to disk."""
        if flush:
            self.send('/save-all flush\n')
        else:
            self.send('/save-all\n')

    def set_auto_save(self, auto_save):
        """Enable or disable server auto-save."""
        if auto_save:
            self.send('/save-on\n')
        else:
            self.send('/save-off\n')

    # Player spawning, teleporting, spreading

    def set_world_spawn(self, x, y, z):
        """Set world spawn point."""
        self.send('/setworldspawn %s %s %s\n' % (x, y, z))

    def set_player_spawn(self, player, x, y, z):
        """Set player spawn point."""
        self.send('/spawnpoint %s %s %s %s\n' % (player, x, y, z))

    def spread_players(self, x, z, spread_distance, max_range, respect_teams, player):
        """Spread players apart."""
        respect_teams = str(respect_teams).lower()
        self.send('/spreadplayers %s %s %s %s %s %s\n' % (x, z, spread_distance, max_range, respect_teams, player))

    def teleport(self, target, x, y, z, x_rot='~', z_rot='~'):
        """Teleport entities (players, mobs, items, etc.)."""
        self.send('/teleport %s %s %s %s %s %s\n' % (target, x, y, z, x_rot, z_rot))

    def teleport_to(self, target, destination):
        """Teleport one entity to another."""
        self.send('/tp %s %s\n' % (target, destination))
        
    # Summoning

    def summon(self, entity_name, x, y, z, data_tag=''):
        """Summon entity."""
        self.send('/summon %s %s %s %s %\n' % (entity_name, x, y, z, data_tag))

    def summon_at_player(self, player, entity_name, data_tag=''):
        """Summon entity at a player's location."""
        self.send('/execute %s ~ ~ ~ summon %s ~ ~ ~ %s\n' % (player, entity_name, data_tag))

    # World border

    def set_world_border(self, distance, time=''):
        """Specify diameter of world border."""
        self.send('/worldborder set %s %s\n' % (distance, time))
    
    def increase_world_border(self, distance, time=''):
        """Increase diameter of world border."""
        self.send('/worldborder add %s %s\n' % (distance, time))

    def center_world_border(self, x, z):
        """Recenter world border."""
        self.send('/worldborder center %s %s\n' % (x, z))

    def set_world_border_damage_amount(self, damage_per_block):
        """Specify world border damage rate."""
        self.send('/worldborder damage amount %s\n' % damage_per_block)

    def set_world_border_damage_buffer(self, distance):
        """Specify world border damage buffer distance."""
        self.send('/worldborder damage buffer %s\n' % distance)

    def set_world_border_warning_distance(self, distance):
        """Specify world border warning distance."""
        self.send('/worldborder warning distance %s\n' % distance)

    def set_world_border_warning_time(self, time):
        """Specify world border warning time."""
        self.send('/worldborder warning time %s\n' % time)


class ChatHandler:
    def __init__(self, pattern, level, thread, function):
        self.pattern = pattern
        self.level = level
        self.thread = thread
        self.function = function
    
class ServerEvent:
    log_pattern = '^\[(\d{2}:\d{2}:\d{2})\] \[([^/]+)/([^\]]+)\]: (.*)$'
    
    def __init__(self, log_line):
        match = re.match(self.log_pattern, log_line)

        if match:
            self.source = log_line
            self.time = match.group(1)
            self.thread = match.group(2)
            self.level = match.group(3)
            self.message = match.group(4)
            self._process()
        else:
            raise LogParseError('Could not parse line: %s' % log_line)
        
    def __str__(self):
        return self.log_line

    def _process(self): pass

class LoginEvent(ServerEvent):
    def _process(self):
        login_pattern = '^([^\s]+) joined the game$'
        match = re.match(login_pattern, self.message)
        if match:
            self.player = match.group(1)
        else:
            raise LogParseError('Could not parse LoginEvent from message: %s' % self.message)
        
class LogoutEvent(ServerEvent):
    def _process(self):
        logout_pattern = '^([^\s]+) left the game$'
        match = re.match(logout_pattern, self.message)
        if match:
            self.player = match.group(1)
        else:
            raise LogParseError('Could not parse LogoutEvent from message: %s' % self.message)

class DeathEvent(ServerEvent):
    def _process(self):
        death_patterns = ['^(.*) was shot by arrow$',
                          '^(.*) was shot by (.*)$',
                          '^(.*) was shot by (.*) using (.*)$',
                          '^(.*) was pricked to death$',
                          '^(.*) walked into a cactus while trying to escape (.*)$'
                          '^(.*) drowned$',
                          '^(.*) drowned whilst trying to escape (.*)$',
                          '^(.*) experienced kinetic energy$',
                          '^(.*) blew up$',
                          '^(.*) was blown up by (.*)$',
                          '^(.*) hit the ground too hard$',
                          '^(.*) fell from a high place$',
                          '^(.*) fell off a ladder$',
                          '^(.*) fell off some vines$',
                          '^(.*) fell out of the water$',
                          '^(.*) fell into a patch of fire$',
                          '^(.*) fell into a patch of cacti$',
                          '^(.*) was doomed to fall by (.*)$',
                          '^(.*) was shot off some vines by (.*)$',
                          '^(.*) was shot off a ladder by (.*)$',
                          '^(.*) was blown from a high place by (.*)$',
                          '^(.*) was squashed by a falling anvil$',
                          '^(.*) was squashed by a falling block$',
                          '^(.*) went up in flames$',
                          '^(.*) burned to death$',
                          '^(.*) was burnt to a crisp whilst fighting (.*)$',
                          '^(.*) walked into a fire whilst fighting (.*)$',
                          '^(.*) tried to swim in lava$',
                          '^(.*) tried to swim in lava while trying to escape (.*)$',
                          '^(.*) was struck by lightning$',
                          '^(.*) was slain by (.*)$',
                          '^(.*) was slain by (.*) using (.*)$',
                          '^(.*) got finished off by (.*)$',
                          '^(.*) got finished off by (.*) using (.*)$',
                          '^(.*) was fireballed by (.*)$',
                          '^(.*) was killed by magic$',
                          '^(.*) was killed by (.*) using magic$',
                          '^(.*) starved to death$',
                          '^(.*) fell out of the world$',
                          '^(.*) fell from a high place and fell out of the world$',
                          '^(.*) withered away$',
                          '^(.*) was pummeled by (.*)$'
        ]

        for pattern in death_patterns:
            match = re.match(pattern, self.message)
            if match:
                self.player = match.group(1)
                self.killer = match.group(2) if len(match.groups()) > 1 else None
                self.weapon = match.group(3) if len(match.groups()) > 2 else None
                break
        else:
            raise LogParseError('Could not parse DeathEvent from message: %s' % self.message)

class ChatEvent(ServerEvent):
    def _process(self):
        chat_pattern = '^<([^>]+)> (.*)$'
        match = re.match(chat_pattern, self.message)
        if match:
            self.player = match.group(1)
            self.chat = match.group(2)
        else:
            raise LogParseError('Could not parse ChatEvent from message: %s' % self.message)
        
class LogParseError(Exception): pass
