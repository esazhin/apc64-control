-----------------------------------------------------------------------------------------------
-- apc64Session.lua  —  APC64 "Ableton" Session View -> MPC Clip Matrix + mixer surface.
-- Maps the APC64's DAW-mode protocol (note/CC + LED codes from Bitwig's MIT extension) onto the
-- MPC Lua controller API. Interop script; not an Akai file.
--
-- Limitation (proven, both ends): the 8 faders transmit 14-bit pitch-bend on ch 1-8 (captured off
-- the device). The MPC can't receive it two independent ways: the script layer has no pitch-bend
-- handler (only NoteOn/NoteOff/CC/Sysex), and native MIDI-Learn has no pitch-bend source type. So
-- the fader channel strip is impossible on a stock MPC without a PB->CC proxy. See README.md.
-----------------------------------------------------------------------------------------------

local deviceName = "apc64Session";
local dawPortIndex = 0;
local noteZeroIsBottomLeft = true;

-- ---- APC64 control map ----
local GRID_START, GRID_END = 0x00, 0x3F;
local SCENE_BASE    = 0x70;
local TRACKS_BASE   = 0x64;
local TRACKCTL_BASE = 0x40;
local MODE_REC, MODE_MUTE, MODE_SOLO, MODE_STOP = 0x6C, 0x6D, 0x6E, 0x6F;
local NAV_DOWN, NAV_UP, NAV_LEFT, NAV_RIGHT = 0x5E, 0x5F, 0x60, 0x61;
local PLAY, REC, STOP = 0x5B, 0x5C, 0x5D;
local SHIFT = 0x78;
local STRIP_DEVICE, STRIP_VOLUME, STRIP_PAN = 0x79, 0x7A, 0x7B;
local STRIP_SENDS, STRIP_CHANNEL, STRIP_OFF = 0x7C, 0x7D, 0x7E;
local CLEAR, DUPLICATE, QUANTIZE, FIXED, UNDO = 0x49, 0x4A, 0x4B, 0x4C, 0x4D;

-- ---- LED encodings ----
local S_OFF, S_DIM, S_MID, S_FULL = 0, 1, 3, 7;
local S_PULSE2, S_BLINK8 = 11, 14;
local B_DIM, B_MID, B_FULL = 0, 2, 6;
local B_PULSE2, B_BLINK8 = 10, 13;
-- Launchpad/Ableton "Live" palette indices (velocity = colour index; verified on device)
local C_OFF, C_WHITE, C_RED, C_GREEN = 0, 3, 5, 21;
local C_AMBER, C_YELLOW, C_BLUE, C_CYAN = 9, 13, 45, 32;

-- ---- sysex (no F0/F7) ----
local introSysex       = string.char(0x47,0x00,0x53,0x1B,0x00,0x01,0x00);
local sessionModeSysex = string.char(0x47,0x00,0x53,0x19,0x00,0x01,0x00);
local identityRequest  = string.char(0x7E,0x7F,0x06,0x01);
local dawModeOnSysex   = string.char(0x47,0x00,0x53,0x1C,0x00,0x01,0x01);
local dawModeOffSysex  = string.char(0x47,0x00,0x53,0x1C,0x00,0x01,0x00);

-- ---- runtime state ----
local shiftHeld = false;
local trackMode = "stop";
local firstCol, firstRow = 0, 0;
local apertureTracks = false;
local P = {};
local colorTest, colorPage = false, 0;   -- QUANTIZE cycles a velocity->colour swatch for calibration

-----------------------------------------------------------------------------------------------
-- helpers
-----------------------------------------------------------------------------------------------
local function sendSysex(s) apc64Session.midiOut.SendMIDISysex(s, dawPortIndex); end
local function led1(note, code) apc64Session.midiOut.SendMIDINoteOn(0, note, code, dawPortIndex); end
local function ledRgb(note, behavior, color) apc64Session.midiOut.SendMIDINoteOn(behavior, note, color, dawPortIndex); end

local function oledText(row, text)
    local content = string.char(row) .. text .. string.char(0x00);
    sendSysex(string.char(0x47,0x00,0x53,0x10,0x00,#content) .. content);
end

-- APC64 LED palette = the Launchpad / Ableton "Live" 128-colour palette (velocity = index).
-- Verified against on-device swatch taps: 1=grey, 3=white, 17=lime, 32=cyan, 53=magenta.
-- colorIndex(argb) returns the velocity whose palette RGB is nearest the MPC clip colour.
local PAL = { -- PAL[v] = {R,G,B} for velocity v (0..127)
  [0]={0,0,0}, [1]={28,28,28}, [2]={124,124,124}, [3]={252,252,252}, [4]={255,78,72}, [5]={254,10,0}, [6]={90,0,0}, [7]={24,0,2},
  [8]={255,188,99}, [9]={255,87,0}, [10]={90,29,0}, [11]={36,24,2}, [12]={253,253,33}, [13]={253,253,0}, [14]={88,88,0}, [15]={24,24,0},
  [16]={129,253,43}, [17]={64,253,1}, [18]={22,88,0}, [19]={19,40,1}, [20]={53,253,43}, [21]={0,254,0}, [22]={0,88,1}, [23]={0,24,0},
  [24]={53,252,71}, [25]={0,254,0}, [26]={0,88,1}, [27]={0,24,0}, [28]={50,253,127}, [29]={0,253,58}, [30]={1,88,20}, [31]={0,28,14},
  [32]={47,252,177}, [33]={0,251,145}, [34]={1,87,50}, [35]={1,24,16}, [36]={57,190,255}, [37]={0,167,255}, [38]={1,64,81}, [39]={0,16,24},
  [40]={65,134,255}, [41]={0,80,255}, [42]={1,26,90}, [43]={1,6,25}, [44]={71,71,255}, [45]={0,0,254}, [46]={0,0,90}, [47]={0,0,24},
  [48]={131,71,255}, [49]={80,0,255}, [50]={22,0,103}, [51]={10,0,50}, [52]={255,72,254}, [53]={255,0,254}, [54]={90,0,90}, [55]={24,0,24},
  [56]={251,78,131}, [57]={255,7,83}, [58]={90,2,27}, [59]={33,1,16}, [60]={255,25,1}, [61]={154,53,0}, [62]={122,81,1}, [63]={62,101,0},
  [64]={1,56,0}, [65]={0,84,50}, [66]={0,83,127}, [67]={0,0,254}, [68]={1,68,77}, [69]={26,0,209}, [70]={124,124,124}, [71]={32,32,32},
  [72]={255,10,0}, [73]={186,253,0}, [74]={172,236,0}, [75]={86,253,0}, [76]={0,136,0}, [77]={1,252,123}, [78]={0,167,255}, [79]={2,26,255},
  [80]={53,0,255}, [81]={120,0,255}, [82]={180,23,126}, [83]={65,32,0}, [84]={255,74,1}, [85]={130,225,0}, [86]={102,253,0}, [87]={0,254,0},
  [88]={0,254,0}, [89]={69,253,97}, [90]={1,251,203}, [91]={80,134,255}, [92]={39,77,200}, [93]={132,122,237}, [94]={211,12,255}, [95]={255,6,90},
  [96]={255,125,1}, [97]={184,177,0}, [98]={138,253,0}, [99]={129,93,0}, [100]={58,40,2}, [101]={13,76,5}, [102]={0,80,55}, [103]={19,20,41},
  [104]={16,31,90}, [105]={106,60,24}, [106]={172,4,1}, [107]={225,81,54}, [108]={220,105,0}, [109]={254,225,0}, [110]={153,225,1}, [111]={96,181,0},
  [112]={27,28,49}, [113]={220,253,84}, [114]={118,251,185}, [115]={150,152,255}, [116]={139,98,255}, [117]={64,64,64}, [118]={116,116,116}, [119]={222,252,252},
  [120]={162,4,1}, [121]={52,1,0}, [122]={0,210,1}, [123]={0,65,1}, [124]={184,177,0}, [125]={60,48,0}, [126]={180,93,0}, [127]={76,19,0},
};
-- Per-colour overrides: exact MPC colour 0xRRGGBB -> preferred APC velocity.
-- For hues (purples/magentas) where nearest-RGB looks perceptually off, pin the pad
-- colour by hand. Tap the swatch to find the velocity you want, then set it here.
local OVERRIDE = {
    [0x6F00FF] = 79,   -- violet -> 2,26,255  (Eugene-picked)
    [0xB200FF] = 80,   -- grape  -> 53,0,255  (Eugene-picked)
};
local function colorIndex(argb)
    if not argb then return C_WHITE; end
    local rv,gv,bv = (argb>>16)&0xFF, (argb>>8)&0xFF, argb&0xFF;
    if rv<12 and gv<12 and bv<12 then return 0; end
    local ov = OVERRIDE[(rv<<16)|(gv<<8)|bv];
    if ov then return ov; end
    local best, bestD = C_WHITE, math.huge;
    for v=1,127 do
        local p = PAL[v];
        local dr,dg,db = rv-p[1], gv-p[2], bv-p[3];
        local d = dr*dr + dg*dg + db*db;
        if d < bestD then bestD, best = d, v; end
    end
    return best;
end

local function noteForCell(col, row)
    if noteZeroIsBottomLeft then return (7-row)*8 + col; end
    return row*8 + col;
end
local function cellForNote(note)
    local col, line = note%8, note//8;
    if noteZeroIsBottomLeft then return col, 7-line; end
    return col, line;
end

-- values & fields ------------------------------------------------------------
local function hasField(obj, name)
    local ok, v = pcall(function() return obj[name]; end);
    return ok and v ~= nil;
end
local function readVal(obj, name)
    if not obj or not name then return nil; end
    local ok, v = pcall(function() return obj[name].value; end);
    if ok then return v; end
    return nil;
end
local function truthy(v) return v == true or (type(v) == "number" and v ~= 0); end

local function trackCount()
    local ok, n = pcall(function() return mpc.tracks.normalTracks.Count.value; end);
    return ok and n or 0;
end
-- aperture's per-column track (colour/select; follows horizontal scroll)
local function apTrack(col)
    local ok, t = pcall(function() return apc64Session.clipMatrixAperture.trackProperties[col]; end);
    if ok and t ~= nil then apertureTracks = true; return t; end
    return nil;
end
-- the real mixer track for this aperture column (Mute/Solo/RecordArm)
local function mixTrack(col)
    local idx = firstCol + col;
    if idx >= trackCount() then return nil; end
    local ok, t = pcall(function() return mpc.tracks.normalTracks[idx]; end);
    return ok and t or nil;
end

-- toggle a mixer function: call the action method, else write a state property
local function doTrackAction(track, kind)
    if not track then return; end
    local actions = ({ mute={"Mute"}, solo={"Solo"}, rec={"RecArm"} })[kind];
    local states  = ({ mute={"Muted","IsMuted","Mute"}, solo={"Soloed","Solo"},
                       rec ={"RecArm"} })[kind];
    for _,n in ipairs(actions) do if pcall(function() track[n](); end) then return; end end
    for _,n in ipairs(states) do
        local ok, v = pcall(function() return track[n].value; end);
        if ok and v ~= nil then
            if type(v)=="boolean" then pcall(function() track[n].value = not v; end); return;
            elseif type(v)=="number" then pcall(function() track[n].value = (v~=0) and 0 or 1; end); return; end
        end
    end
end
local function stateOn(track, kind)
    local names = ({ mute={"Muted","IsMuted","Mute"}, solo={"Soloed","Solo"},
                     rec ={"RecArm"} })[kind];
    for _,n in ipairs(names) do local v = readVal(track, n); if v ~= nil then return truthy(v); end end
    return false;
end

local function resolveProps()
    local ap, mt = apTrack(0), mixTrack(0);
    local function pick(obj, cands)
        if obj then for _,n in ipairs(cands) do if hasField(obj, n) then return n; end end end
        return nil;
    end
    P.colour = pick(ap, { "Colour","Color" }) or pick(mt, { "Colour","Color" });
    P.sel    = pick(ap, { "Selected","IsSelected" });
    P.hasIdx = hasField(ap, "Index");
    P.hasMute = pick(mt, { "Mute","Muted","IsMuted" }) or "nil";
end
local function selectedTrackIndex()
    local ok, i = pcall(function() return mpc.tracks.currentTrack.Index.value; end);
    return ok and i or -1;
end

-----------------------------------------------------------------------------------------------
-- drawing
-----------------------------------------------------------------------------------------------
local function clipAt(col, row)
    local ok, c = pcall(function() return apc64Session.clipMatrixAperture.clipProperties[col][row]; end);
    return ok and c or nil;
end

local function drawCell(col, row)
    local clip = clipAt(col, row);
    if not clip then ledRgb(noteForCell(col,row), B_FULL, C_OFF); return; end
    local state = clip.State.value;
    local behaviour, velocity = B_FULL, 0;
    if state < 2 then
        if clip.Selected.value then behaviour, velocity = B_MID, C_WHITE; else velocity = C_OFF; end
    elseif state == 2 then
        velocity = colorIndex(clip.Colour.value);
    elseif state < 6 then velocity = C_GREEN;
    else velocity = C_RED; end
    if state==3 or state==5 or state==6 or state==8 or state==9 or state==11 then behaviour = B_BLINK8;
    elseif state > 3 then behaviour = B_PULSE2; end
    ledRgb(noteForCell(col,row), behaviour, velocity);
end
local function drawGrid()
    for col=0,7 do for row=0,7 do drawCell(col,row); end end
end

local function rowHasClips(row)
    local any, queued = false, false;
    for col=0,7 do
        local c = clipAt(col,row);
        if c then
            local s = c.State.value;
            if s >= 2 then any = true; end
            if s==3 or s==5 or s==6 or s==8 or s==9 or s==11 then queued = true; end
        end
    end
    return any, queued;
end
local function drawScenes()
    for row=0,7 do
        local any, queued = rowHasClips(row);
        led1(SCENE_BASE+row, queued and S_BLINK8 or (any and S_DIM or S_OFF));
    end
end

local function trackSelected(ap, col)
    local v = readVal(ap, P.sel);
    if v ~= nil then return truthy(v); end
    local idx = (ap and readVal(ap,"Index")) or (firstCol+col);
    return idx == selectedTrackIndex();
end
local function drawTrackSelect()
    for col=0,7 do
        local ap = apTrack(col) or mixTrack(col);
        if not ap then ledRgb(TRACKS_BASE+col, B_FULL, C_OFF);
        elseif trackSelected(ap, col) then ledRgb(TRACKS_BASE+col, B_FULL, C_WHITE);
        else ledRgb(TRACKS_BASE+col, B_MID, colorIndex(readVal(ap, P.colour))); end
    end
end

local function drawTrackControl()
    for col=0,7 do
        local note = TRACKCTL_BASE+col;
        local ap = apTrack(col) or mixTrack(col);
        if not ap then ledRgb(note, B_FULL, C_OFF);
        elseif trackMode == "mute" then ledRgb(note, stateOn(mixTrack(col),"mute") and B_FULL or B_DIM, C_AMBER);
        elseif trackMode == "solo" then ledRgb(note, stateOn(mixTrack(col),"solo") and B_FULL or B_DIM, C_BLUE);
        elseif trackMode == "rec"  then ledRgb(note, stateOn(mixTrack(col),"rec")  and B_FULL or B_DIM, C_RED);
        else ledRgb(note, B_DIM, colorIndex(readVal(ap, P.colour))); end
    end
end

local function drawTrackRow() drawTrackSelect(); drawTrackControl(); end

local function drawModes()
    led1(MODE_STOP, trackMode=="stop" and S_FULL or S_DIM);
    led1(MODE_MUTE, trackMode=="mute" and S_FULL or S_DIM);
    led1(MODE_SOLO, trackMode=="solo" and S_FULL or S_DIM);
    led1(MODE_REC,  trackMode=="rec"  and S_FULL or S_DIM);
end
local function drawTransport()
    local playing = false; pcall(function() playing = mpc.sequencer.Playing.value; end);
    local rec = 0; pcall(function() rec = mpc.sequencer.RecordState.value; end);
    led1(PLAY, playing and S_FULL or S_DIM);
    led1(STOP, S_DIM);
    led1(REC,  (rec ~= 0) and S_FULL or S_DIM);
end
local function drawNav()
    led1(NAV_UP, firstRow > 0 and S_FULL or S_DIM);
    led1(NAV_DOWN, S_FULL);
    led1(NAV_LEFT, firstCol > 0 and S_FULL or S_DIM);
    led1(NAV_RIGHT, (firstCol + 8 < trackCount()) and S_FULL or S_DIM);
end
local function drawExtra()
    led1(CLEAR, S_DIM); led1(DUPLICATE, S_DIM); led1(QUANTIZE, S_DIM); led1(FIXED, S_DIM); led1(UNDO, S_DIM);
    led1(STRIP_VOLUME, S_FULL);
    for _,n in ipairs({ STRIP_DEVICE, STRIP_PAN, STRIP_SENDS, STRIP_CHANNEL, STRIP_OFF }) do led1(n, S_DIM); end
end
-- calibration swatch: each pad shows a velocity (base..base+63) at full brightness.
-- pad velocity = (row*8 + col) + colorPage*64, where row 0 = BOTTOM.
local function drawColorTest()
    for col=0,7 do for row=0,7 do
        local vel = (row*8 + col) + colorPage*64;
        if vel > 127 then vel = 0; end
        ledRgb(noteForCell(col,row), B_FULL, vel);
    end end
    oledText(0, "CTEST base " .. (colorPage*64));
    oledText(1, "QUANTIZE: next/exit");
end

local function drawAll()
    if colorTest then drawColorTest(); return; end
    drawGrid(); drawScenes(); drawTrackRow(); drawModes(); drawTransport(); drawNav(); drawExtra();
end

-----------------------------------------------------------------------------------------------
-- aperture navigation — MoveTo(col,row) absolute, Move/Scroll fallbacks
-----------------------------------------------------------------------------------------------
local function stopAllClips()
    local aps = apc64Session.clipMatrixAperture;
    if not pcall(function() aps.StopAllClips(); end) then
        local n = math.max(8, trackCount());
        for c=0,n-1 do pcall(function() aps.StopClipsOnTrack(c); end); end
    end
end

local function apertureMove(dc, dr)
    local cols = trackCount();
    firstCol = math.max(0, math.min(firstCol + dc, math.max(0, cols - 8)));
    firstRow = math.max(0, firstRow + dr);
    local ap = apc64Session.clipMatrixAperture;
    -- aperture is detached from the TUI (see OnLoad); MoveTo positions the window absolutely
    local moved = pcall(function() ap.MoveTo(firstCol, firstRow); end)
               or pcall(function() ap.Move(firstCol, firstRow); end)
               or pcall(function() ap.Scroll(dc, dr); end);
    oledText(2, "pos " .. firstCol .. "," .. firstRow .. (moved and "" or " !"));
    drawAll();
end

-----------------------------------------------------------------------------------------------
-- bindings
-----------------------------------------------------------------------------------------------
local function singleNotes()
    return { SCENE_BASE,SCENE_BASE+1,SCENE_BASE+2,SCENE_BASE+3,SCENE_BASE+4,SCENE_BASE+5,SCENE_BASE+6,SCENE_BASE+7,
        TRACKS_BASE,TRACKS_BASE+1,TRACKS_BASE+2,TRACKS_BASE+3,TRACKS_BASE+4,TRACKS_BASE+5,TRACKS_BASE+6,TRACKS_BASE+7,
        TRACKCTL_BASE,TRACKCTL_BASE+1,TRACKCTL_BASE+2,TRACKCTL_BASE+3,TRACKCTL_BASE+4,TRACKCTL_BASE+5,TRACKCTL_BASE+6,TRACKCTL_BASE+7,
        MODE_REC,MODE_MUTE,MODE_SOLO,MODE_STOP, NAV_DOWN,NAV_UP,NAV_LEFT,NAV_RIGHT,
        PLAY,REC,STOP,SHIFT, CLEAR,DUPLICATE,QUANTIZE,FIXED,UNDO,
        STRIP_DEVICE,STRIP_VOLUME,STRIP_PAN,STRIP_SENDS,STRIP_CHANNEL,STRIP_OFF };
end
local function bindAllNotes(add)
    local m = apc64Session.mappings.script;
    for ch=0,15 do for note=GRID_START,GRID_END do   -- grid pads on any channel
        if add then m.AddNoteToScript(ch,note); else m.RemoveNoteToScript(ch,note); end
    end end
    for note=0,127 do                                 -- consume ALL ch0 notes (buttons, encoder, strays)
        if add then m.AddNoteToScript(0,note); else m.RemoveNoteToScript(0,note); end
    end
end

local function registerListeners()
    for col=0,7 do for row=0,7 do
        local c = clipAt(col,row);
        if c then
            pcall(function() c.State:listen(function() drawGrid(); drawScenes(); end, deviceName); end);
            pcall(function() c.Colour:listen(function() drawGrid(); end, deviceName); end);
            pcall(function() c.Selected:listen(function() drawGrid(); end, deviceName); end);
        end
    end end
    -- sentinel: top-left clip changes on horizontal scroll -> resync the track row (for MPC-side nav)
    local c0 = clipAt(0,0);
    if c0 then
        pcall(function() c0.State:listen(function() drawTrackRow(); end, deviceName.."_trk"); end);
        pcall(function() c0.Colour:listen(function() drawTrackRow(); end, deviceName.."_trk"); end);
    end
    pcall(function() mpc.sequencer.Playing:listen(function() drawTransport(); end, deviceName); end);
    pcall(function() mpc.sequencer.RecordState:listen(function() drawTransport(); end, deviceName); end);
    pcall(function() mpc.tracks.currentTrack.Index:listen(function() drawTrackSelect(); end, deviceName); end);
end
local function clearListeners()
    for col=0,7 do for row=0,7 do
        local c = clipAt(col,row);
        if c then pcall(function() c.State:stopListening(deviceName); end);
                  pcall(function() c.Colour:stopListening(deviceName); end);
                  pcall(function() c.Selected:stopListening(deviceName); end); end
    end end
    local c0 = clipAt(0,0);
    if c0 then pcall(function() c0.State:stopListening(deviceName.."_trk"); end);
               pcall(function() c0.Colour:stopListening(deviceName.."_trk"); end); end
    pcall(function() mpc.sequencer.Playing:stopListening(deviceName); end);
    pcall(function() mpc.sequencer.RecordState:stopListening(deviceName); end);
    pcall(function() mpc.tracks.currentTrack.Index:stopListening(deviceName); end);
end

-----------------------------------------------------------------------------------------------
-- REQUIRED FUNCTIONS (called from C++)
-----------------------------------------------------------------------------------------------
function apc64Session.HandleMIDINoteOn(channel, note, velocity)
    if note == SHIFT then shiftHeld = velocity > 0; return; end
    if velocity == 0 then return; end
    local ap = apc64Session.clipMatrixAperture;

    if note >= GRID_START and note <= GRID_END then
        local col,row = cellForNote(note);
        if colorTest then   -- swatch mode: tapping a pad reports that pad's exact velocity
            local vel = (row*8 + col) + colorPage*64;
            if vel > 127 then vel = 0; end
            oledText(0, "swatch tap");
            oledText(1, "velocity = "..vel);
            return;
        end
        ap.SelectClip(col,row);
        if shiftHeld then   -- shift+tap = probe: show this clip's raw colour + state, don't launch
            local cl = clipAt(col,row);
            local function num(field)
                if not cl then return "-"; end
                local ok, v = pcall(function() return cl[field].value; end);
                if not ok or v == nil then return "nil"; end
                if type(v)=="number" then
                    if math.type(v)=="integer" then return string.format("%X", v & 0xFFFFFFFFFF); end
                    return string.format("f%.4g", v);
                end
                return type(v);
            end
            local pick = cl and colorIndex(readVal(cl,"Colour")) or "-";
            oledText(0, "clip "..col..","..row.." vel="..tostring(pick));
            oledText(1, "Colour="..num("Colour"));
            oledText(2, "State="..num("State"));
            return;
        end
        ap.TriggerClip(col,row);

    elseif note >= SCENE_BASE and note < SCENE_BASE+8 then
        if shiftHeld and note == SCENE_BASE+7 then stopAllClips();  -- shift+bottom scene = stop all
        else ap.TriggerRow(note - SCENE_BASE); end

    elseif note >= TRACKS_BASE and note < TRACKS_BASE+8 then
        pcall(function() ap.SelectTrack(note - TRACKS_BASE); end);

    elseif note >= TRACKCTL_BASE and note < TRACKCTL_BASE+8 then
        local col = note - TRACKCTL_BASE;
        if trackMode == "mute" then doTrackAction(mixTrack(col), "mute");
        elseif trackMode == "solo" then doTrackAction(mixTrack(col), "solo");
        elseif trackMode == "rec" then doTrackAction(mixTrack(col), "rec");
        else pcall(function() ap.StopClipsOnTrack(col); end); end
        drawTrackControl();

    elseif note == MODE_STOP then trackMode="stop"; drawModes(); drawTrackControl();
    elseif note == MODE_MUTE then trackMode="mute"; drawModes(); drawTrackControl();
    elseif note == MODE_SOLO then trackMode="solo"; drawModes(); drawTrackControl();
    elseif note == MODE_REC  then trackMode="rec";  drawModes(); drawTrackControl();

    elseif note == NAV_LEFT  then apertureMove(-1,0);
    elseif note == NAV_RIGHT then apertureMove(1,0);
    elseif note == NAV_UP    then apertureMove(0,1);
    elseif note == NAV_DOWN  then apertureMove(0,-1);

    elseif note == QUANTIZE then
        if not colorTest then colorTest, colorPage = true, 0;
        elseif colorPage == 0 then colorPage = 1;
        else colorTest = false; end
        drawAll();

    elseif note == PLAY then pcall(function() mpc.sequencer.TogglePlayStart(); end);
    elseif note == STOP then
        if shiftHeld then stopAllClips();
        else pcall(function() mpc.sequencer.Stop(); end); end
    elseif note == REC then pcall(function() mpc.sequencer.Record(); end);
    end
end

function apc64Session.HandleMIDINoteOff(channel, note, velocity)
    if note == SHIFT then shiftHeld = false; end
end
function apc64Session.HandleMIDICC(channel, cc, value) end
function apc64Session.HandleMIDISysex(sysexChars)
    if sysexChars == sessionModeSysex then drawAll(); end
end
function apc64Session.HandleTimer() end

function apc64Session.OnLoad()
    mpc.ui.ShowTUIFeedback("APC64 Session loaded");
    apc64Session.mappings.script.SetHandleSysex(true);
    sendSysex(introSysex); sendSysex(sessionModeSysex);
    sendSysex(identityRequest); sendSysex(dawModeOnSysex);

    pcall(function()
        apc64Session.clipMatrixAperture.SetColumns(8);
        apc64Session.clipMatrixAperture.SetRows(8);
        apc64Session.clipMatrixAperture.SetLabel("APC64");
        apc64Session.clipMatrixAperture.Show();
    end);
    -- detach from the MPC touchscreen view so the APC arrows control the window independently
    pcall(function() apc64Session.clipMatrixAperture.SetFollowsTUIActiveMatrix(false); end);
    pcall(function() apc64Session.clipMatrixAperture.SetFollowsTUI(false); end);
    pcall(function() apc64Session.clipMatrixAperture.MoveTo(0, 0); end);

    pcall(resolveProps);
    oledText(0, "MPC Session");
    -- arm field types: f=function(method) u=userdata(property) t=table n=nil
    pcall(function()
        local t = mixTrack(0);
        local abbr = { ["nil"]="n", ["function"]="f", userdata="u", table="t", number="N", boolean="b" };
        local function tp(n)
            local ok, x = pcall(function() return t[n]; end);
            if not ok then return "x"; end
            return abbr[type(x)] or "?";
        end
        oledText(1, "RecArm="..tp("RecArm").." Mute="..tp("Mute").." Solo="..tp("Solo"));
    end);
    -- COLOUR FORMAT PROBE: dump the raw Colour.value of track 0 and the first
    -- few visible clips so we can decode the real encoding (packed ARGB? index?).
    pcall(function()
        local function col(obj)
            if not obj then return "-"; end
            local ok, v = pcall(function() return obj.Colour.value; end);
            if not ok or v == nil then return "nil"; end
            if type(v) == "number" then
                if math.type(v) == "integer" then return string.format("%X", v & 0xFFFFFFFFFF); end
                return string.format("f%.3g", v);
            end
            return type(v);
        end
        oledText(2, "T0="..col(mixTrack(0)).." T1="..col(mixTrack(1)));
        local first;
        for r=0,7 do for c=0,7 do
            local cl = clipAt(c,r);
            if cl and not first then first = cl; end
        end end
        oledText(3, "clip="..col(first));
    end);

    pcall(bindAllNotes, true);
    pcall(registerListeners);
    pcall(drawAll);
end

function apc64Session.OnUnload()
    pcall(clearListeners);
    pcall(bindAllNotes, false);
    apc64Session.mappings.script.SetHandleSysex(false);
    pcall(function() apc64Session.clipMatrixAperture.Hide(); end);
    sendSysex(dawModeOffSysex);
end
