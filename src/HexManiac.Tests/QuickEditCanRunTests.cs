using HavenSoft.HexManiac.Core;
using HavenSoft.HexManiac.Core.Models;
using HavenSoft.HexManiac.Core.ViewModels.QuickEditItems;
using HavenSoft.HexManiac.Core.ViewModels;
using Xunit;

namespace HavenSoft.HexManiac.Tests {
   /// <summary>
   /// The Utilities menu asks every quick edit whether it can run each time the user changes tabs,
   /// so a quick edit that is only for one exact file must be able to say "no" without reading the whole file.
   /// </summary>
   public class QuickEditCanRunTests : BaseViewModelTestClass {
      [Fact]
      public void ApplyCFRUPatch_SomethingThatIsNotAViewPort_CanNotRun() {
         Assert.False(new ApplyCFRUPatch().CanRun(null));
      }

      [Fact]
      public void ApplyCFRUPatch_ASmallFile_CanNotRun() {
         Assert.False(new ApplyCFRUPatch().CanRun(ViewPort));
      }

      [Fact]
      public void ApplyCFRUPatch_FireRedCodeButNotTheVanillaSize_CanNotRun() {
         SetGameCode("BPRE0");
         Assert.False(new ApplyCFRUPatch().CanRun(ViewPort));
      }

      // "Apply CUBE" is asked the same question each time the tab changes, and is grayed out the same way

      private static ApplyCubePatch NewApplyCube() => new ApplyCubePatch(new EditorViewModel(new StubFileSystem()));

      [Fact]
      public void ApplyCubePatch_SomethingThatIsNotAViewPort_CanNotRun() {
         Assert.False(NewApplyCube().CanRun(null));
      }

      [Fact]
      public void ApplyCubePatch_ASmallFile_CanNotRun() {
         Assert.False(NewApplyCube().CanRun(ViewPort));
      }

      [Fact]
      public void ApplyCubePatch_EmeraldCodeButNotTheVanillaSize_CanNotRun() {
         SetGameCode("BPEE0");
         Assert.False(NewApplyCube().CanRun(ViewPort));
      }

      [Fact]
      public void ApplyCubePatch_VanillaSizeButAnotherGame_CanNotRun() {
         var firered = new byte[VanillaRomSpec.EmeraldUsV10.Length];
         System.Text.Encoding.ASCII.GetBytes("BPRE").CopyTo(firered, 0xAC);
         var tab = new ViewPort("FireRed.gba", new PokemonModel(firered, singletons: Singletons), InstantDispatch.Instance, Singletons);
         Assert.False(NewApplyCube().CanRun(tab));
      }

      [Fact]
      public void ApplyCubePatch_VanillaSizeAndEmeraldCodeButOtherContent_CanNotRun() {
         var almostEmerald = new byte[VanillaRomSpec.EmeraldUsV10.Length];
         System.Text.Encoding.ASCII.GetBytes("BPEE").CopyTo(almostEmerald, 0xAC);
         var tab = new ViewPort("Hack.gba", new PokemonModel(almostEmerald, singletons: Singletons), InstantDispatch.Instance, Singletons);
         Assert.False(NewApplyCube().CanRun(tab));
      }
   }
}
