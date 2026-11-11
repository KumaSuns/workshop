using System.Net;
using Common.Logging;
using Common.Logging.Simple;
using Makaretu.Dns;

namespace MirrorDisplay;

/// <summary>
/// iPhone の NWBrowser が探す _mirrdev._tcp.local を告知する。
/// </summary>
sealed class MdnsAdvertiser : IDisposable
{
    readonly ServiceDiscovery discovery;
    readonly ServiceProfile profile;

    public MdnsAdvertiser(string instanceName, int port, IReadOnlyList<IPAddress> addresses)
    {
        try
        {
            LogManager.Adapter = new NoOpLoggerFactoryAdapter();
        }
        catch (InvalidOperationException)
        {
            // ロガーは既に設定済み。
        }

        discovery = new ServiceDiscovery();
        profile = new ServiceProfile(
            new DomainName(instanceName),
            new DomainName("_mirrdev._tcp"),
            (ushort)port,
            addresses.Count == 0 ? null : addresses);
        discovery.Advertise(profile);
        Task.Run(Announce);
    }

    void Announce()
    {
        try
        {
            discovery.Announce(profile);
        }
        catch
        {
            // 問い合わせへの応答は Advertise 側が続ける。
        }
    }

    public void Dispose()
    {
        try
        {
            discovery.Unadvertise();
        }
        catch
        {
            // 終了中。
        }

        discovery.Dispose();
    }
}
