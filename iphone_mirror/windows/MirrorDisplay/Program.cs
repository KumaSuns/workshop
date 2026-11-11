using System.Buffers.Binary;
using System.Diagnostics;
using System.Net;
using System.Net.NetworkInformation;
using System.Net.Sockets;
using System.Runtime.InteropServices;
using System.Text;

namespace MirrorDisplay;

static class Program
{
    [STAThread]
    static void Main()
    {
        ApplicationConfiguration.Initialize();
        Application.Run(new ViewerForm());
    }
}

sealed class ViewerForm : Form
{
    const int TcpPort = 47777;
    const int BeaconPort = 47778;

    readonly PictureBox picture = new()
    {
        Dock = DockStyle.Fill,
        SizeMode = PictureBoxSizeMode.Zoom,
        BackColor = Color.FromArgb(8, 12, 22),
    };
    readonly Panel tools = new()
    {
        Dock = DockStyle.Right,
        Width = 480,
        BackColor = Color.FromArgb(8, 12, 22),
    };
    readonly Panel stage = new()
    {
        Dock = DockStyle.Fill,
        BackColor = Color.FromArgb(8, 12, 22),
    };
    readonly GameAudioPanel side = new();
    readonly Panel bar = new()
    {
        Dock = DockStyle.Bottom,
        Height = 40,
        BackColor = Color.FromArgb(8, 12, 22),
        Padding = new Padding(0, 4, 8, 4),
    };
    readonly Label status = new()
    {
        Dock = DockStyle.Fill,
        TextAlign = ContentAlignment.MiddleLeft,
        ForeColor = Color.FromArgb(190, 255, 236),
        BackColor = Color.FromArgb(8, 12, 22),
        Padding = new Padding(12, 0, 0, 0),
        Font = new Font("Bahnschrift", 13f, FontStyle.Bold, GraphicsUnit.Pixel),
    };
    readonly Button copyButton = new()
    {
        Text = "画像をコピー",
        Location = new Point(12, 12),
        Size = new Size(160, 36),
        FlatStyle = FlatStyle.Flat,
        ForeColor = Color.FromArgb(190, 255, 236),
        BackColor = Color.FromArgb(16, 40, 48),
        Font = new Font("Bahnschrift", 13f, FontStyle.Bold, GraphicsUnit.Pixel),
        Cursor = Cursors.Hand,
    };
    readonly Button watchButton = new()
    {
        Text = "解析オン",
        Location = new Point(180, 12),
        Size = new Size(120, 36),
        FlatStyle = FlatStyle.Flat,
        ForeColor = Color.White,
        BackColor = Color.FromArgb(196, 32, 40),
        Font = new Font("Yu Gothic UI", 14f, FontStyle.Bold, GraphicsUnit.Pixel),
        Cursor = Cursors.Hand,
    };
    bool watchGame = true;
    readonly Panel startFrame = new()
    {
        BackColor = Color.White,
    };
    readonly Label startText = new()
    {
        Dock = DockStyle.Fill,
        TextAlign = ContentAlignment.MiddleCenter,
        ForeColor = Color.FromArgb(20, 24, 32),
        BackColor = Color.White,
        Font = new Font("Yu Gothic UI", 18f, FontStyle.Bold, GraphicsUnit.Pixel),
        Text = "",
    };
    readonly PrepBoard prepBoard = new();
    readonly Panel playFrame = new()
    {
        BackColor = Color.White,
    };
    readonly PlayColumn playColumn = new();
    readonly Label playTime = new()
    {
        Dock = DockStyle.Fill,
        TextAlign = ContentAlignment.MiddleCenter,
        ForeColor = Color.FromArgb(20, 24, 32),
        BackColor = Color.White,
        Font = new Font("Yu Gothic UI", 28f, FontStyle.Bold, GraphicsUnit.Pixel),
        Text = "",
    };
    readonly System.Windows.Forms.Timer playTick = new() { Interval = 100 };
    readonly Stopwatch playClock = new();
    bool playTiming;
    string playSeen = "";
    int playSeenCount;
    string heldTsum = "";
    bool[] heldOn = new bool[7];
    bool heldPrep;
    int? playCoin;
    int? playResult;
    string moneyRate = "";
    string moneyProfit = "";
    long nextMoneyTick;
    int moneyBusy;
    static readonly int[] ItemCost = { 500, 500, 500, 1000, 1500, 1800, 1200 };
    readonly Button shortcutButton = new()
    {
        Dock = DockStyle.Right,
        Width = 168,
        Text = "起動アイコンを作る",
        FlatStyle = FlatStyle.Flat,
        ForeColor = Color.FromArgb(190, 255, 236),
        BackColor = Color.FromArgb(16, 40, 48),
        Font = new Font("Bahnschrift", 13f, FontStyle.Bold, GraphicsUnit.Pixel),
        Cursor = Cursors.Hand,
    };
    const string ReceiverName = "このPC";

    readonly PcmPlayer audio = new();
    readonly object clientGate = new();
    readonly object frameGate = new();

    TcpListener? listener;
    UdpClient? beacon;
    TcpClient? client;
    CancellationTokenSource? lifetime;
    MdnsAdvertiser? publisher;
    byte[]? latestJpeg;
    bool showing;
    float appliedAspect;

    public ViewerForm()
    {
        Text = "ミラー";
        var icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath);
        if (icon != null)
        {
            Icon = icon;
        }
        BackColor = Color.FromArgb(8, 12, 22);
        ClientSize = new Size(960 + tools.Width + side.Width, 540);
        tools.Paint += (_, e) =>
        {
            var bounds = tools.ClientRectangle;
            bounds.Width -= 1;
            bounds.Height -= 1;
            using var pen = new Pen(Color.FromArgb(80, 255, 214));
            e.Graphics.DrawRectangle(pen, bounds);
        };
        StartPosition = FormStartPosition.CenterScreen;
        shortcutButton.FlatAppearance.BorderColor = Color.FromArgb(80, 255, 214);
        shortcutButton.FlatAppearance.BorderSize = 1;
        shortcutButton.FlatAppearance.MouseOverBackColor = Color.FromArgb(24, 64, 72);
        shortcutButton.FlatAppearance.MouseDownBackColor = Color.FromArgb(12, 28, 36);
        shortcutButton.Click += (_, _) => CreateLaunchIcon();
        copyButton.FlatAppearance.BorderColor = Color.FromArgb(80, 255, 214);
        copyButton.FlatAppearance.BorderSize = 1;
        copyButton.FlatAppearance.MouseOverBackColor = Color.FromArgb(24, 64, 72);
        copyButton.FlatAppearance.MouseDownBackColor = Color.FromArgb(12, 28, 36);
        copyButton.Click += (_, _) => CopyCurrentImage();
        watchButton.FlatAppearance.BorderSize = 1;
        watchButton.Click += (_, _) => ToggleWatch();
        ApplyWatchButton();
        startFrame.Location = new Point(12, copyButton.Bottom + 12);
        startFrame.Size = new Size(tools.Width - 24, 64);
        startFrame.Paint += (_, e) =>
        {
            var bounds = startFrame.ClientRectangle;
            bounds.Width -= 1;
            bounds.Height -= 1;
            using var pen = new Pen(Color.FromArgb(80, 255, 214));
            e.Graphics.DrawRectangle(pen, bounds);
        };
        startFrame.Controls.Add(startText);
        prepBoard.Location = new Point(12, startFrame.Bottom + 12);
        prepBoard.Size = new Size(tools.Width - 24, 112);
        PrepScreen.Start();
        prepBoard.LoadIcons(PrepScreen.IconsDirectory);
        playFrame.Location = new Point(12, prepBoard.Bottom + 12);
        playFrame.Size = new Size(tools.Width - 24, 72);
        playFrame.Paint += (_, e) =>
        {
            var bounds = playFrame.ClientRectangle;
            bounds.Width -= 1;
            bounds.Height -= 1;
            using var pen = new Pen(Color.FromArgb(80, 255, 214));
            e.Graphics.DrawRectangle(pen, bounds);
        };
        playFrame.Controls.Add(playTime);
        playColumn.Location = new Point(12, playFrame.Bottom + 12);
        playColumn.Size = new Size(tools.Width - 24, playColumn.Height);
        playTick.Tick += (_, _) =>
        {
            if (playTiming)
            {
                ShowPlayTime();
            }
        };
        playTick.Start();
        tools.Controls.Add(copyButton);
        tools.Controls.Add(watchButton);
        tools.Controls.Add(startFrame);
        tools.Controls.Add(prepBoard);
        tools.Controls.Add(playFrame);
        tools.Controls.Add(playColumn);
        bar.Controls.Add(status);
        bar.Controls.Add(shortcutButton);
        stage.Controls.Add(picture);
        stage.Controls.Add(bar);
        Controls.Add(stage);
        Controls.Add(tools);
        Controls.Add(side);
        side.OutputChanged += (_, _) =>
        {
            audio.SetOutput(side.Volume / 100f, side.Muted);
            SaveVolume(side.Volume, side.Muted);
        };
        var (volume, muted) = LoadVolume();
        side.Restore(volume, muted);
        status.Text = "待っています  " + string.Join("  ", LanAddresses());
    }

    protected override void OnShown(EventArgs e)
    {
        base.OnShown(e);
        var area = Screen.FromControl(this).WorkingArea;
        int chrome = Height - ClientSize.Height;
        ClientSize = new Size(ClientSize.Width, Math.Max(1, area.Height - chrome));
        int x = Left;
        x = Math.Clamp(x, area.Left, Math.Max(area.Left, area.Right - Width));
        Location = new Point(x, area.Top);
        lifetime = new CancellationTokenSource();
        var token = lifetime.Token;
        try
        {
            listener = new TcpListener(IPAddress.Any, TcpPort);
            listener.Start();
            beacon = new UdpClient();
            beacon.EnableBroadcast = true;
            try
            {
                publisher = new MdnsAdvertiser(ReceiverName, TcpPort, ReachableAddresses().ToArray());
            }
            catch
            {
                // UDP の合図は続ける。Bonjour が使えなくても、同じ手順で受信できる。
            }

            Task.Run(() => AcceptLoop(token));
            Task.Run(() => BeaconLoop(token));
            SetStatus("iPhone からの画面を待っています  " + string.Join("  ", ReachableAddresses()));
        }
        catch (Exception ex)
        {
            status.Text = "開けませんでした。 " + ex.Message;
        }
    }

    protected override void OnFormClosed(FormClosedEventArgs e)
    {
        lifetime?.Cancel();
        try { listener?.Stop(); } catch { /* closing */ }
        publisher?.Dispose();
        beacon?.Dispose();
        lock (clientGate)
        {
            client?.Close();
        }
        audio.Dispose();
        picture.Image?.Dispose();
        base.OnFormClosed(e);
    }

    void AcceptLoop(CancellationToken token)
    {
        while (!token.IsCancellationRequested && listener != null)
        {
            TcpClient next;
            try
            {
                next = listener.AcceptTcpClient();
            }
            catch
            {
                return;
            }

            next.NoDelay = true;
            lock (clientGate)
            {
                client?.Close();
                client = next;
            }

            SetStatus("iPhone が接続しました");
            try
            {
                ReadClient(next.GetStream(), token);
            }
            catch
            {
                /* disconnected */
            }

            lock (clientGate)
            {
                if (ReferenceEquals(client, next))
                {
                    client = null;
                }
            }

            next.Close();
            if (!token.IsCancellationRequested)
            {
                SetStatus("切断されました。待っています");
            }
        }
    }

    void ReadClient(NetworkStream stream, CancellationToken token)
    {
        var lengthBytes = new byte[4];
        while (!token.IsCancellationRequested)
        {
            ReadExact(stream, lengthBytes);
            int length = BinaryPrimitives.ReadInt32BigEndian(lengthBytes);
            if (length < 1 || length > 4_000_000)
            {
                return;
            }

            var body = new byte[length];
            ReadExact(stream, body);
            var payload = body.AsSpan(1);
            switch (body[0])
            {
                case 1:
                    ShowJpeg(payload.ToArray());
                    break;
                case 2:
                    PlayPcm(payload);
                    break;
            }
        }
    }

    static void ReadExact(NetworkStream stream, byte[] buffer)
    {
        int offset = 0;
        while (offset < buffer.Length)
        {
            int read = stream.Read(buffer, offset, buffer.Length - offset);
            if (read == 0)
            {
                throw new IOException("closed");
            }

            offset += read;
        }
    }

    void ShowJpeg(byte[] jpeg)
    {
        lock (frameGate)
        {
            latestJpeg = jpeg;
            if (showing)
            {
                return;
            }

            showing = true;
        }

        try
        {
            BeginInvoke(DrainFrames);
        }
        catch (InvalidOperationException)
        {
            lock (frameGate)
            {
                showing = false;
            }
        }
    }

    void DrainFrames()
    {
        while (true)
        {
            byte[]? jpeg;
            lock (frameGate)
            {
                jpeg = latestJpeg;
                latestJpeg = null;
                if (jpeg == null)
                {
                    showing = false;
                    return;
                }
            }

            try
            {
                using var stream = new MemoryStream(jpeg);
                using var decoded = Image.FromStream(stream);
                var copy = new Bitmap(decoded);
                var previous = picture.Image;
                picture.Image = copy;
                previous?.Dispose();
                status.Text = "受信中";
                if (watchGame)
                {
                    bool holdPrep = playTiming;
                    try
                    {
                        startText.Text = StartScreen.Match(copy) ?? "";
                        string mark = PlayMark.Match(copy);
                        if (mark == "go")
                        {
                            holdPrep = true;
                        }

                        if (holdPrep)
                        {
                            if (heldPrep)
                            {
                                prepBoard.Show(heldTsum, heldOn);
                            }
                        }
                        else
                        {
                            var prep = PrepScreen.Read(copy);
                            if (prep.Screen)
                            {
                                heldTsum = prep.Tsum;
                                heldOn = prep.On;
                                heldPrep = true;
                                prepBoard.Show(heldTsum, heldOn);
                            }
                            else if (heldPrep)
                            {
                                prepBoard.Show(heldTsum, heldOn);
                            }
                        }

                        NotePlay(mark);
                        playColumn.SetLamps(
                            (mark == "go" || playTiming) && mark != "timeup",
                            false,
                            false,
                            mark == "timeup");
                        NoteMoney(copy);
                    }
                    catch
                    {
                        startText.Text = "";
                        if (heldPrep)
                        {
                            prepBoard.Show(heldTsum, heldOn);
                        }
                    }
                }
                FitWindow(copy);
            }
            catch
            {
                status.Text = "映像を表示できません";
            }
        }
    }

    void ToggleWatch()
    {
        watchGame = !watchGame;
        if (playTiming)
        {
            if (watchGame)
            {
                playClock.Start();
            }
            else
            {
                playClock.Stop();
            }
        }

        ApplyWatchButton();
    }

    void ApplyWatchButton()
    {
        if (watchGame)
        {
            watchButton.Text = "解析オン";
            watchButton.BackColor = Color.FromArgb(196, 32, 40);
            watchButton.FlatAppearance.BorderColor = Color.FromArgb(255, 160, 160);
            watchButton.FlatAppearance.MouseOverBackColor = Color.FromArgb(220, 48, 56);
            watchButton.FlatAppearance.MouseDownBackColor = Color.FromArgb(150, 20, 28);
        }
        else
        {
            watchButton.Text = "解析オフ";
            watchButton.BackColor = Color.FromArgb(32, 88, 196);
            watchButton.FlatAppearance.BorderColor = Color.FromArgb(160, 196, 255);
            watchButton.FlatAppearance.MouseOverBackColor = Color.FromArgb(48, 112, 220);
            watchButton.FlatAppearance.MouseDownBackColor = Color.FromArgb(20, 60, 150);
        }
    }

    static string VolumePath()
    {
        return Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "MirrorDisplay",
            "volume.txt");
    }

    static (int Volume, bool Muted) LoadVolume()
    {
        try
        {
            string[] lines = File.ReadAllLines(VolumePath());
            int volume = int.Parse(lines[0]);
            bool muted = lines.Length > 1 && lines[1] == "1";
            return (Math.Clamp(volume, 0, 100), muted);
        }
        catch
        {
            return (100, false);
        }
    }

    static void SaveVolume(int volume, bool muted)
    {
        try
        {
            string path = VolumePath();
            Directory.CreateDirectory(Path.GetDirectoryName(path)!);
            File.WriteAllLines(path, new[] { volume.ToString(), muted ? "1" : "0" });
        }
        catch
        {
            /* 次回の起動では前回の値に戻らない */
        }
    }

    void NotePlay(string mark)
    {
        if (mark.Length == 0)
        {
            playSeen = "";
            playSeenCount = 0;
            return;
        }

        if (mark == playSeen)
        {
            playSeenCount++;
        }
        else
        {
            playSeen = mark;
            playSeenCount = 1;
        }

        if (playSeenCount < 2)
        {
            return;
        }

        if (mark == "go" && !playTiming)
        {
            playClock.Restart();
            playTiming = true;
            ShowPlayTime();
            return;
        }

        if (mark == "timeup" && playTiming)
        {
            playClock.Stop();
            playTiming = false;
            ShowPlayTime();
        }
    }

    void ShowPlayTime()
    {
        var elapsed = playClock.Elapsed;
        int tenth = elapsed.Milliseconds / 100;
        playTime.Text = $"{(int)elapsed.TotalMinutes}:{elapsed.Seconds:00}.{tenth}";
    }

    void NoteMoney(Bitmap image)
    {
        if (Environment.TickCount64 < nextMoneyTick)
        {
            return;
        }

        if (Interlocked.CompareExchange(ref moneyBusy, 1, 0) != 0)
        {
            return;
        }

        nextMoneyTick = Environment.TickCount64 + 400;
        string path = Path.Combine(Path.GetTempPath(), "mirror-coin-frame.png");
        try
        {
            image.Save(path, System.Drawing.Imaging.ImageFormat.Png);
        }
        catch
        {
            Interlocked.Exchange(ref moneyBusy, 0);
            return;
        }

        _ = Task.Run(() =>
        {
            try
            {
                var (coinText, resultText) = CoinRead.Ask(path);
                int? coin = Digits(coinText);
                int? result = Digits(resultText);
                if (coin == null && result == null)
                {
                    return;
                }

                BeginInvoke(() =>
                {
                    if (IsDisposed)
                    {
                        return;
                    }

                    if (coin != null)
                    {
                        playCoin = coin.Value;
                    }
                    else if (result != null)
                    {
                        playResult = result.Value;
                        moneyRate = "";
                        if (playCoin is int earned && earned > 0 && result.Value > 0)
                        {
                            moneyRate = "×" + (result.Value / (double)earned).ToString("0.0", System.Globalization.CultureInfo.InvariantCulture);
                        }

                        int cost = 0;
                        if (heldPrep)
                        {
                            for (int i = 0; i < heldOn.Length && i < ItemCost.Length; i++)
                            {
                                if (heldOn[i])
                                {
                                    cost += ItemCost[i];
                                }
                            }
                        }

                        moneyProfit = (result.Value - cost).ToString("N0", System.Globalization.CultureInfo.InvariantCulture);
                    }

                    ShowMoney();
                });
            }
            catch
            {
                /* 読めなかった回は、前の数字を残す */
            }
            finally
            {
                Interlocked.Exchange(ref moneyBusy, 0);
            }
        });
    }

    void ShowMoney()
    {
        string coin = playCoin is int earned ? earned.ToString("N0", System.Globalization.CultureInfo.InvariantCulture) : "";
        string result = playResult is int got ? got.ToString("N0", System.Globalization.CultureInfo.InvariantCulture) : "";
        playColumn.SetMoney(coin, result, moneyRate, moneyProfit);
    }

    static int? Digits(string text)
    {
        var chars = text.Where(char.IsDigit).ToArray();
        if (chars.Length == 0 || chars.Length > 8)
        {
            return null;
        }

        return int.TryParse(new string(chars), out int value) ? value : null;
    }

    void CopyCurrentImage()
    {
        var image = picture.Image;
        if (image == null)
        {
            status.Text = "コピーする画像がありません";
            return;
        }

        using var copy = new Bitmap(image);
        Clipboard.SetImage(copy);
        status.Text = "画像をコピーしました";
    }

    void FitWindow(Image image)
    {
        if (WindowState == FormWindowState.Maximized || image.Width < 2 || image.Height < 2)
        {
            return;
        }

        float aspect = image.Width / (float)image.Height;
        if (Math.Abs(aspect - appliedAspect) <= 0.02f)
        {
            return;
        }

        appliedAspect = aspect;
        var screen = Screen.FromControl(this).WorkingArea;
        int maxWidth = Math.Min(image.Width, (int)(screen.Width * 0.72));
        int maxHeight = Math.Min(image.Height, (int)(screen.Height * 0.86) - bar.Height);
        int pictureWidth = maxWidth;
        int pictureHeight = (int)Math.Round(pictureWidth / aspect);
        if (pictureHeight > maxHeight)
        {
            pictureHeight = Math.Max(1, maxHeight);
            pictureWidth = Math.Max(1, (int)Math.Round(pictureHeight * aspect));
        }

        var center = new Point(Left + Width / 2, Top + Height / 2);
        ClientSize = new Size(pictureWidth + tools.Width + side.Width, pictureHeight + bar.Height);
        int x = center.X - Width / 2;
        int y = center.Y - Height / 2;
        x = Math.Clamp(x, screen.Left, Math.Max(screen.Left, screen.Right - Width));
        y = Math.Clamp(y, screen.Top, Math.Max(screen.Top, screen.Bottom - Height));
        Location = new Point(x, y);
    }

    protected override void WndProc(ref Message m)
    {
        const int sizing = 0x0214;
        if (m.Msg == sizing && appliedAspect > 0.05f && WindowState == FormWindowState.Normal)
        {
            var rect = Marshal.PtrToStructure<WindowRect>(m.LParam);
            Constrain(ref rect, m.WParam.ToInt32());
            Marshal.StructureToPtr(rect, m.LParam, false);
        }

        base.WndProc(ref m);
    }

    void Constrain(ref WindowRect rect, int edge)
    {
        int frameWidth = Width - ClientSize.Width;
        int frameHeight = Height - ClientSize.Height;
        int width = Math.Max(160, rect.Right - rect.Left - frameWidth - side.Width - tools.Width);
        int height = Math.Max(160, rect.Bottom - rect.Top - frameHeight - bar.Height);
        bool fromHeight = edge is 3 or 6;
        if (fromHeight)
        {
            width = Math.Max(1, (int)Math.Round(height * appliedAspect));
        }
        else
        {
            height = Math.Max(1, (int)Math.Round(width / appliedAspect));
        }

        int windowWidth = width + side.Width + tools.Width + frameWidth;
        int windowHeight = height + bar.Height + frameHeight;
        if (edge is 1 or 4 or 7)
        {
            rect.Left = rect.Right - windowWidth;
        }
        else
        {
            rect.Right = rect.Left + windowWidth;
        }

        if (edge is 3 or 4 or 5)
        {
            rect.Top = rect.Bottom - windowHeight;
        }
        else
        {
            rect.Bottom = rect.Top + windowHeight;
        }
    }

    [StructLayout(LayoutKind.Sequential)]
    struct WindowRect
    {
        public int Left;
        public int Top;
        public int Right;
        public int Bottom;
    }

    void PlayPcm(ReadOnlySpan<byte> payload)
    {
        if (payload.Length < 8)
        {
            return;
        }

        int sampleRate = BinaryPrimitives.ReadInt32BigEndian(payload);
        int channels = BinaryPrimitives.ReadUInt16BigEndian(payload.Slice(4));
        int bits = BinaryPrimitives.ReadUInt16BigEndian(payload.Slice(6));
        if (bits != 16 || sampleRate < 8000 || sampleRate > 192000 || channels is < 1 or > 2)
        {
            return;
        }

        audio.Play(payload.Slice(8).ToArray(), sampleRate, channels);
    }

    void BeaconLoop(CancellationToken token)
    {
        var packet = BeaconPacket();
        while (!token.IsCancellationRequested)
        {
            try
            {
                foreach (var address in BroadcastAddresses())
                {
                    beacon?.Send(packet, packet.Length, new IPEndPoint(address, BeaconPort));
                }
            }
            catch
            {
                /* next tick */
            }

            if (token.WaitHandle.WaitOne(1000))
            {
                return;
            }
        }
    }

    static byte[] BeaconPacket()
    {
        var name = Encoding.UTF8.GetBytes(ReceiverName);
        var packet = new byte[6 + name.Length];
        packet[0] = (byte)'M';
        packet[1] = (byte)'I';
        packet[2] = (byte)'R';
        packet[3] = (byte)'R';
        BinaryPrimitives.WriteUInt16BigEndian(packet.AsSpan(4), TcpPort);
        name.CopyTo(packet.AsSpan(6));
        return packet;
    }

    void CreateLaunchIcon()
    {
        try
        {
            string exe = Application.ExecutablePath;
            string desktop = Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory);
            string link = Path.Combine(desktop, "ミラー.lnk");
            Type? shellType = Type.GetTypeFromProgID("WScript.Shell");
            if (shellType == null || Activator.CreateInstance(shellType) is not object shell)
            {
                status.Text = "起動アイコンを作れませんでした";
                return;
            }

            dynamic shortcut = ((dynamic)shell).CreateShortcut(link);
            shortcut.TargetPath = exe;
            shortcut.WorkingDirectory = Path.GetDirectoryName(exe) ?? "";
            shortcut.Description = "iPhone の画面をこのPCに出す";
            shortcut.IconLocation = exe + ",0";
            shortcut.Save();
            status.Text = "デスクトップに「ミラー」を作りました";
        }
        catch (Exception ex)
        {
            status.Text = "起動アイコンを作れませんでした。 " + ex.Message;
        }
    }

    void SetStatus(string text)
    {
        if (IsDisposed)
        {
            return;
        }

        BeginInvoke(() => status.Text = text);
    }

    static IEnumerable<IPAddress> LanAddresses()
    {
        foreach (var (nic, address) in LocalAddresses())
        {
            _ = nic;
            yield return address;
        }
    }

    static IEnumerable<IPAddress> ReachableAddresses()
    {
        var addresses = LocalAddresses()
            .Where(item => !IsLinkLocal(item.Address) && !IsVirtual(item.Nic))
            .Select(item => item.Address)
            .ToArray();
        return addresses.Length == 0 ? LanAddresses() : addresses;
    }

    static IEnumerable<(NetworkInterface Nic, IPAddress Address)> LocalAddresses()
    {
        foreach (var nic in NetworkInterface.GetAllNetworkInterfaces())
        {
            if (nic.OperationalStatus != OperationalStatus.Up || nic.NetworkInterfaceType == NetworkInterfaceType.Loopback)
            {
                continue;
            }

            foreach (var unicast in nic.GetIPProperties().UnicastAddresses)
            {
                if (unicast.Address.AddressFamily != AddressFamily.InterNetwork || IPAddress.IsLoopback(unicast.Address))
                {
                    continue;
                }

                yield return (nic, unicast.Address);
            }
        }
    }

    static bool IsLinkLocal(IPAddress address)
    {
        var bytes = address.GetAddressBytes();
        return bytes.Length == 4 && bytes[0] == 169 && bytes[1] == 254;
    }

    static bool IsVirtual(NetworkInterface nic)
    {
        return nic.Name.Contains("vEthernet", StringComparison.OrdinalIgnoreCase);
    }

    static IEnumerable<IPAddress> BroadcastAddresses()
    {
        yield return IPAddress.Broadcast;
        foreach (var nic in NetworkInterface.GetAllNetworkInterfaces())
        {
            if (nic.OperationalStatus != OperationalStatus.Up)
            {
                continue;
            }

            foreach (var unicast in nic.GetIPProperties().UnicastAddresses)
            {
                if (unicast.Address.AddressFamily != AddressFamily.InterNetwork || unicast.IPv4Mask == null)
                {
                    continue;
                }

                var ip = unicast.Address.GetAddressBytes();
                var mask = unicast.IPv4Mask.GetAddressBytes();
                if (ip.Length != 4 || mask.Length != 4)
                {
                    continue;
                }

                var broadcast = new byte[4];
                for (int i = 0; i < 4; i++)
                {
                    broadcast[i] = (byte)(ip[i] | ~mask[i]);
                }

                yield return new IPAddress(broadcast);
            }
        }
    }
}
