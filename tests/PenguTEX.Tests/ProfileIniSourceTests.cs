using PenguTEX.Assets.Profiles;

namespace PenguTEX.Tests;

/// <summary>Archive lists come only from the INIs the game would read for the profile.</summary>
public sealed class ProfileIniSourceTests
{
    private static (string Instance, string Prefix) PrefixProfile(Fixture f, bool localInis)
    {
        string game = f.Dir("game"); f.Dir("game/Data");
        string prefix = f.Dir("pfx"); f.Dir("pfx/dosdevices");
        f.Text("pfx/drive_c/users/steamuser/Documents/My Games/Skyrim Special Edition/Skyrim.ini",
            "[Archive]\nsArchiveToLoadInMemoryList=Leak.bsa\n");
        f.Text("instance/ModOrganizer.ini", $"[General]\ngamePath={game.Replace("\\", "\\\\")}\nselected_profile=Example\n");
        f.Text("instance/profiles/Example/settings.ini", $"[General]\nLocalSettings={(localInis ? "true" : "false")}\n");
        f.Text("instance/profiles/Example/skyrim.ini", "[Archive]\nsResourceArchiveList=\nsResourceArchiveList2=\n");
        f.Text("instance/profiles/Example/modlist.txt", "");
        return (Path.Combine(f.Root, "instance"), prefix);
    }

    [Fact] public void LocalProfileInisNeverFallBackToDocuments()
    {
        if (OperatingSystem.IsWindows()) return;
        using var f = new Fixture(); var (instance, prefix) = PrefixProfile(f, localInis: true);
        var profile = Mo2Instance.Open(instance, new(WinePrefix: prefix)).OpenProfile("Example");
        Assert.DoesNotContain("Leak.bsa", profile.IniArchives());
        Assert.Empty(profile.IniArchives());
    }

    [Fact] public void SharedProfileInisComeFromTheSelectedPrefix()
    {
        if (OperatingSystem.IsWindows()) return;
        using var f = new Fixture(); var (instance, prefix) = PrefixProfile(f, localInis: false);
        var profile = Mo2Instance.Open(instance, new(WinePrefix: prefix)).OpenProfile("Example");
        Assert.Contains("Leak.bsa", profile.IniArchives());
    }
}
